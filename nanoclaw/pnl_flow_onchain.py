"""On-chain USDT/USDC transfer scrape for PnL capital-flow tags (Polygon RPC logs)."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# keccak256("Transfer(address,address,uint256)")
TRANSFER_EVENT_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4dfe65b"
)
# Polygon PoS ~2s blocks; used for lookback window sizing.
_BLOCKS_PER_HOUR_EST = 1800
_LOG_CHUNK_BLOCKS = 2000
_STABLE_DECIMALS = 6
PNL_FLOW_EVENTS_FILE = ".runtime/pnl_flow_events.jsonl"


def _parse_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_env_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except ValueError:
        return default
    if not math.isfinite(value) or value <= 0.0:
        return default
    return value


def pnl_flow_onchain_enabled() -> bool:
    return _parse_env_bool("PNL_FLOW_ONCHAIN_ENABLED", default=True)


def pnl_flow_onchain_lookback_hours() -> float:
    return _parse_env_positive_float("PNL_FLOW_ONCHAIN_LOOKBACK_HOURS", 168.0)


def pnl_flow_step_min_usd() -> float:
    return _parse_env_positive_float("PNL_FLOW_STEP_MIN_USD", 5.0)


def pnl_flow_wallet() -> str:
    raw = os.getenv("PNL_FLOW_WALLET") or os.getenv("WALLET") or ""
    return str(raw).strip()


def stable_token_addresses() -> list[tuple[str, str]]:
    """Return ``(symbol, checksum_address)`` for USDT + USDC variants."""
    import config

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for symbol, addr in (
        ("USDT", config.USDT),
        ("USDC", config.USDC),
        ("USDC_NATIVE", config.USDC_NATIVE),
    ):
        text = str(addr or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append((symbol, text))
    return out


def wallet_topic_hex(wallet: str) -> str:
    """32-byte topic encoding for an indexed address."""
    body = str(wallet or "").strip().lower().removeprefix("0x")
    if len(body) != 40:
        raise ValueError(f"invalid wallet address: {wallet!r}")
    return "0x" + body.zfill(64)


@dataclass(frozen=True)
class OnchainFlowRecord:
    ts: datetime
    kind: str  # deposit | withdraw
    amount_usd: float
    tx_hash: str
    block_number: int
    token_symbol: str
    token_address: str
    from_address: str
    to_address: str

    def to_jsonl_obj(self) -> dict[str, Any]:
        return {
            "timestamp": self.ts.isoformat(),
            "kind": self.kind,
            "amount_usd": round(float(self.amount_usd), 6),
            "source": "onchain",
            "tx_hash": self.tx_hash,
            "block_number": int(self.block_number),
            "token": self.token_symbol,
            "token_address": self.token_address,
            "from": self.from_address,
            "to": self.to_address,
            "confidence": 1.0,
        }


def _topic_address(topic: Any) -> str:
    if topic is None:
        return ""
    text = topic.hex() if hasattr(topic, "hex") else str(topic)
    text = text.lower().removeprefix("0x")
    if len(text) < 40:
        return ""
    return "0x" + text[-40:]


def _parse_transfer_log(
    log: dict[str, Any],
    *,
    wallet: str,
    token_symbol: str,
    token_address: str,
    block_ts: datetime,
) -> OnchainFlowRecord | None:
    topics = log.get("topics") or []
    if len(topics) < 3:
        return None
    topic0 = topics[0].hex() if hasattr(topics[0], "hex") else str(topics[0])
    if topic0.lower() != TRANSFER_EVENT_TOPIC.lower():
        return None
    from_addr = _topic_address(topics[1])
    to_addr = _topic_address(topics[2])
    wallet_l = wallet.lower()
    if from_addr.lower() == wallet_l:
        kind = "withdraw"
    elif to_addr.lower() == wallet_l:
        kind = "deposit"
    else:
        return None
    data = log.get("data") or b""
    if hasattr(data, "hex"):
        raw_hex = data.hex()
    else:
        raw_hex = str(data).removeprefix("0x")
    if not raw_hex:
        return None
    try:
        amount_raw = int(raw_hex, 16)
    except ValueError:
        return None
    amount_usd = amount_raw / float(10**_STABLE_DECIMALS)
    if not math.isfinite(amount_usd) or amount_usd <= 0.0:
        return None
    tx_hash = log.get("transactionHash")
    if hasattr(tx_hash, "hex"):
        tx_hash = tx_hash.hex()
    tx_hash = str(tx_hash or "").strip()
    if not tx_hash:
        return None
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    block_number = log.get("blockNumber")
    if hasattr(block_number, "__int__"):
        block_number = int(block_number)
    else:
        try:
            block_number = int(str(block_number), 0)
        except (TypeError, ValueError):
            return None
    return OnchainFlowRecord(
        ts=block_ts,
        kind=kind,
        amount_usd=float(amount_usd),
        tx_hash=tx_hash,
        block_number=int(block_number),
        token_symbol=token_symbol,
        token_address=token_address,
        from_address=from_addr,
        to_address=to_addr,
    )


def _iter_block_chunks(from_block: int, to_block: int, *, chunk_size: int) -> Iterable[tuple[int, int]]:
    start = int(from_block)
    end = int(to_block)
    while start <= end:
        chunk_end = min(start + chunk_size - 1, end)
        yield start, chunk_end
        start = chunk_end + 1


def fetch_transfer_logs(
    get_logs: Callable[..., list[dict[str, Any]]],
    *,
    token_address: str,
    wallet: str,
    from_block: int,
    to_block: int,
    direction: str,
    chunk_blocks: int = _LOG_CHUNK_BLOCKS,
) -> list[dict[str, Any]]:
    """Fetch ERC-20 Transfer logs for wallet in/out via ``eth_getLogs``."""
    wallet_topic = wallet_topic_hex(wallet)
    if direction == "in":
        topics: list[Any] = [TRANSFER_EVENT_TOPIC, None, wallet_topic]
    elif direction == "out":
        topics = [TRANSFER_EVENT_TOPIC, wallet_topic, None]
    else:
        raise ValueError(f"unknown direction: {direction!r}")
    out: list[dict[str, Any]] = []
    for chunk_from, chunk_to in _iter_block_chunks(from_block, to_block, chunk_size=chunk_blocks):
        logs = get_logs(
            {
                "fromBlock": chunk_from,
                "toBlock": chunk_to,
                "address": token_address,
                "topics": topics,
            }
        )
        out.extend(logs)
    return out


def scrape_onchain_flows(
    *,
    wallet: str | None = None,
    lookback_hours: float | None = None,
    min_usd: float | None = None,
    now_utc: datetime | None = None,
    get_logs: Callable[..., list[dict[str, Any]]] | None = None,
    get_block_timestamp: Callable[[int], datetime | None] | None = None,
    latest_block_number: int | None = None,
    token_addresses: Sequence[tuple[str, str]] | None = None,
) -> list[OnchainFlowRecord]:
    """Scrape stablecoin Transfer logs in/out of the stage wallet."""
    w = str(wallet or pnl_flow_wallet()).strip()
    if not w:
        return []
    lookback = float(lookback_hours if lookback_hours is not None else pnl_flow_onchain_lookback_hours())
    threshold = float(min_usd if min_usd is not None else pnl_flow_step_min_usd())
    now = now_utc or datetime.now(timezone.utc)
    tokens = list(token_addresses or stable_token_addresses())
    if not tokens:
        return []

    if get_logs is None or latest_block_number is None:
        from web3 import Web3

        from nanoclaw.config import default_json_rpc_url

        w3 = Web3(Web3.HTTPProvider(default_json_rpc_url()[0], request_kwargs={"timeout": 30}))
        latest_block_number = int(w3.eth.block_number)
        if get_block_timestamp is None:

            def _block_ts(block_num: int) -> datetime | None:
                try:
                    block = w3.eth.get_block(block_num)
                except Exception:
                    return None
                ts = block.get("timestamp")
                if ts is None:
                    return None
                return datetime.fromtimestamp(int(ts), tz=timezone.utc)

            get_block_timestamp = _block_ts

        def _get_logs(params: dict[str, Any]) -> list[dict[str, Any]]:
            return list(w3.eth.get_logs(params))

        get_logs = _get_logs

    assert get_logs is not None
    assert latest_block_number is not None
    assert get_block_timestamp is not None

    blocks_back = int(lookback * _BLOCKS_PER_HOUR_EST)
    from_block = max(0, int(latest_block_number) - blocks_back)
    to_block = int(latest_block_number)

    block_ts_cache: dict[int, datetime] = {}
    records: list[OnchainFlowRecord] = []
    seen_tx: set[tuple[str, str, str]] = set()

    for symbol, token_addr in tokens:
        for direction in ("in", "out"):
            logs = fetch_transfer_logs(
                get_logs,
                token_address=token_addr,
                wallet=w,
                from_block=from_block,
                to_block=to_block,
                direction=direction,
            )
            for log in logs:
                block_number = log.get("blockNumber")
                if hasattr(block_number, "__int__"):
                    block_number = int(block_number)
                else:
                    try:
                        block_number = int(str(block_number), 0)
                    except (TypeError, ValueError):
                        continue
                if block_number not in block_ts_cache:
                    ts = get_block_timestamp(block_number)
                    if ts is None:
                        continue
                    block_ts_cache[block_number] = ts
                parsed = _parse_transfer_log(
                    log,
                    wallet=w,
                    token_symbol=symbol,
                    token_address=token_addr,
                    block_ts=block_ts_cache[block_number],
                )
                if parsed is None or parsed.amount_usd < threshold:
                    continue
                dedupe_key = (parsed.tx_hash.lower(), parsed.kind, parsed.token_symbol)
                if dedupe_key in seen_tx:
                    continue
                seen_tx.add(dedupe_key)
                records.append(parsed)

    records.sort(key=lambda r: (r.ts, r.tx_hash))
    cutoff = now - timedelta(hours=lookback)
    return [r for r in records if r.ts >= cutoff]


def read_jsonl_flow_objects(path: Path | str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def merge_onchain_records_into_jsonl(
    records: Sequence[OnchainFlowRecord],
    path: Path | str,
    *,
    min_usd: float | None = None,
) -> tuple[int, int]:
    """Append new on-chain records; return ``(existing_count, appended_count)``."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    threshold = float(min_usd if min_usd is not None else pnl_flow_step_min_usd())
    existing = read_jsonl_flow_objects(p)
    known_tx: set[str] = set()
    for obj in existing:
        tx = str(obj.get("tx_hash") or "").strip().lower()
        if tx:
            known_tx.add(tx)
    appended = 0
    lines: list[str] = []
    if p.is_file():
        lines = [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    for record in records:
        if record.amount_usd < threshold:
            continue
        tx_key = record.tx_hash.lower()
        if tx_key in known_tx:
            continue
        known_tx.add(tx_key)
        lines.append(json.dumps(record.to_jsonl_obj(), ensure_ascii=True, separators=(",", ":")))
        appended += 1
    if appended:
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(existing), appended


@dataclass(frozen=True)
class PnlFlowSyncResult:
    wallet: str
    scraped: int
    appended: int
    existing: int = 0
    records: tuple[OnchainFlowRecord, ...] = ()


def run_pnl_flow_sync(
    *,
    lookback_hours: float | None = None,
    jsonl_path: Path | str | None = None,
    dry_run: bool = False,
    get_logs: Callable[..., list[dict[str, Any]]] | None = None,
    get_block_timestamp: Callable[[int], datetime | None] | None = None,
    latest_block_number: int | None = None,
    token_addresses: Sequence[tuple[str, str]] | None = None,
    now_utc: datetime | None = None,
) -> PnlFlowSyncResult | None:
    """Scrape on-chain flows and merge into jsonl. Returns None when disabled or wallet unset."""
    if not pnl_flow_onchain_enabled():
        return None
    wallet = pnl_flow_wallet()
    if not wallet:
        return None
    records = scrape_onchain_flows(
        wallet=wallet,
        lookback_hours=lookback_hours,
        now_utc=now_utc,
        get_logs=get_logs,
        get_block_timestamp=get_block_timestamp,
        latest_block_number=latest_block_number,
        token_addresses=token_addresses,
    )
    record_tuple = tuple(records)
    if dry_run:
        return PnlFlowSyncResult(
            wallet=wallet,
            scraped=len(records),
            appended=0,
            records=record_tuple,
        )
    path = jsonl_path or PNL_FLOW_EVENTS_FILE
    existing, appended = merge_onchain_records_into_jsonl(records, path)
    return PnlFlowSyncResult(
        wallet=wallet,
        scraped=len(records),
        appended=appended,
        existing=existing,
        records=record_tuple,
    )
