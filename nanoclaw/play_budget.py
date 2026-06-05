"""Daily X-SIGNAL / USDC_TO_EQUITY entry budget for small books (V4-play lab guardrail)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config as cfg

_LOG_PREFIX = "[nanoclaw] PLAY BUDGET"
_CYCLE_TS_RE = re.compile(r"=== CYCLE (\d+)")
_TRADE_ATTRIBUTION_ENTRY_RE = re.compile(
    r"\[nanoclaw\]\s+TRADE_ATTRIBUTION\s+tx=(0x[0-9a-fA-F]+).*?\bdir=USDC_TO_EQUITY\b",
    re.IGNORECASE,
)
_XSIGNAL_STF_SUCCESS_RE = re.compile(
    r"X-SIGNAL STF\s*\|\s*EXEC SUCCESS\b.*?\btx=(0x[0-9a-fA-F]+)",
    re.IGNORECASE,
)


def _enabled() -> bool:
    return bool(getattr(cfg, "PLAY_BUDGET_ENABLED", False))


def _total_ceiling_usd() -> float:
    return float(getattr(cfg, "PLAY_BUDGET_TOTAL_USD_CEILING", 200.0))


def _max_fills_per_utc_day() -> int:
    return max(0, int(getattr(cfg, "PLAY_BUDGET_MAX_FILLS_PER_UTC_DAY", 2)))


def _default_log_path() -> Path:
    from scripts.pnl_report import LOG_FILE

    return Path(LOG_FILE)


def _utc_day_window(now_utc: datetime | None = None) -> tuple[datetime, datetime]:
    now = now_utc or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def count_xsignal_entry_fills(
    log_path: Path | str,
    *,
    since_utc: datetime | None = None,
    until_utc: datetime | None = None,
) -> int:
    """Count USDC_TO_EQUITY / X-SIGNAL entry fills (deduped by tx hash)."""
    path = Path(log_path)
    if not path.is_file():
        return 0
    since_ts = since_utc.timestamp() if since_utc is not None else None
    until_ts = until_utc.timestamp() if until_utc is not None else None
    last_ts = 0
    seen_tx: set[str] = set()
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CYCLE_TS_RE.search(line)
        if m:
            last_ts = int(m.group(1))
            continue
        if last_ts <= 0:
            continue
        if since_ts is not None and last_ts < since_ts:
            continue
        if until_ts is not None and last_ts >= until_ts:
            continue
        tx_hex = None
        attr = _TRADE_ATTRIBUTION_ENTRY_RE.search(line)
        if attr:
            tx_hex = attr.group(1).lower()
        else:
            stf = _XSIGNAL_STF_SUCCESS_RE.search(line)
            if stf:
                tx_hex = stf.group(1).lower()
        if not tx_hex or tx_hex in seen_tx:
            continue
        seen_tx.add(tx_hex)
        n += 1
    return n


def entry_allows(
    *,
    total_usd: float,
    log_path: Path | str | None = None,
    now_utc: datetime | None = None,
) -> tuple[bool, str | None]:
    """Return (allowed, block_reason). Inactive when disabled or book >= ceiling."""
    if not _enabled():
        return True, None
    ceiling = _total_ceiling_usd()
    if float(total_usd) + 1e-9 >= ceiling:
        return True, None
    day_start, day_end = _utc_day_window(now_utc)
    fills = count_xsignal_entry_fills(
        log_path or _default_log_path(),
        since_utc=day_start,
        until_utc=day_end,
    )
    limit = _max_fills_per_utc_day()
    if fills >= limit:
        return False, (
            f"play_budget_exhausted | fills={fills}/{limit} | "
            f"total=${float(total_usd):.2f} < ${ceiling:.0f}"
        )
    return True, None


def log_play_budget_block(*, reason: str, fills: int | None = None, total_usd: float) -> None:
    limit = _max_fills_per_utc_day()
    if fills is None:
        day_start, day_end = _utc_day_window()
        fills = count_xsignal_entry_fills(
            _default_log_path(),
            since_utc=day_start,
            until_utc=day_end,
        )
    print(
        f"{_LOG_PREFIX} | BLOCK | {reason} | fills={fills}/{limit} | total=${float(total_usd):.2f}",
        flush=True,
    )
