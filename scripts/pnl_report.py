#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from modules.baseline import resolve_portfolio_baseline_usd

LOG_FILE = "real_cron.log"
PORTFOLIO_HISTORY_FILE = "portfolio_history.csv"
SESSION_BASELINE_FILE = "portfolio_session_baseline.json"
MANUAL_PATTERN = re.compile(
    r"MANUAL CORRECT BALANCE.*USDC=\$?([\d.]+).*WMATIC=\$?([\d.]+).*USDT=\$?([\d.]+).*Source=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
WALLET_PATTERN = re.compile(r"WALLET BALANCE.*USDC=\$?([\d.]+)")
REAL_PATTERN = re.compile(
    r"Real USDT:\s*\$?([\d.]+)\s*\|\s*USDC:\s*\$?([\d.]+)\s*\|\s*WMATIC:\s*\$?([\d.]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BalanceSnapshot:
    usdt: float
    usdc: float
    wmatic: float
    total: float
    source: str
    logger_source: str | None = None


def extract_snapshots(log_file: Path) -> list[BalanceSnapshot]:
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    snapshots: list[BalanceSnapshot] = []
    pending_wallet: tuple[int, float] | None = None

    for idx, line in enumerate(lines):
        manual_match = MANUAL_PATTERN.search(line)
        if manual_match:
            usdc = float(manual_match.group(1))
            wmatic = float(manual_match.group(2))
            usdt = float(manual_match.group(3))
            logger_source = manual_match.group(4)
            snapshots.append(
                BalanceSnapshot(
                    usdt=usdt,
                    usdc=usdc,
                    wmatic=wmatic,
                    total=usdc + usdt + wmatic,
                    source="manual",
                    logger_source=logger_source,
                )
            )
            continue

        wallet_match = WALLET_PATTERN.search(line)
        if wallet_match:
            pending_wallet = (idx, float(wallet_match.group(1)))
            continue

        real_match = REAL_PATTERN.search(line)
        if not real_match:
            continue

        usdt = float(real_match.group(1))
        usdc = float(real_match.group(2))
        wmatic = float(real_match.group(3))
        source = "real"

        if pending_wallet and (idx - pending_wallet[0]) <= 5:
            usdc = pending_wallet[1]
            source = "paired"
        pending_wallet = None

        snapshots.append(
            BalanceSnapshot(
                usdt=usdt,
                usdc=usdc,
                wmatic=wmatic,
                total=usdc + usdt + wmatic,
                source=source,
            )
        )

    return snapshots


def _source_rank(snapshot: BalanceSnapshot) -> int:
    if snapshot.source == "manual" and snapshot.logger_source in {"BotLogger", "AutoLogger"}:
        return 0
    if snapshot.source == "manual":
        return 1
    if snapshot.source == "paired":
        return 2
    return 3


def _source_label(snapshot: BalanceSnapshot) -> str:
    if snapshot.source == "manual" and snapshot.logger_source:
        return f"MANUAL ({snapshot.logger_source})"
    if snapshot.source == "paired":
        return "WALLET+REAL (paired)"
    if snapshot.source == "real":
        return "Real USDT line"
    return "MANUAL"


def get_current_balance():
    snapshots = extract_snapshots(Path(LOG_FILE))
    if not snapshots:
        return None

    for rank in (0, 1, 2, 3):
        for snapshot in reversed(snapshots):
            if _source_rank(snapshot) != rank:
                continue
            if snapshot.total <= 5:
                continue
            if snapshot.source in {"paired", "real"} and snapshot.wmatic >= 15:
                continue
            return {
                "usdt": snapshot.usdt,
                "usdc": snapshot.usdc,
                "wmatic": snapshot.wmatic,
                "total": snapshot.total,
                "source": _source_label(snapshot),
            }

    return None

def get_recent_trades(n=8):
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    trades = []
    for line in reversed(lines):
        if any(kw in line for kw in ["REAL TX HASH", "Swap executed", "PROTECTION TRIGGERED", "Swap confirmed"]):
            trades.append(line.strip()[:130])
            if len(trades) >= n:
                break
    return list(reversed(trades))


def _pct_change(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def _parse_iso_ts(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_session_baseline(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_session_baseline(path: Path, total: float, now_utc: datetime) -> dict:
    payload = {
        "session_start_total": float(total),
        "session_started_at": now_utc.isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return payload


def resolve_session_baseline(current_total: float, *, reset: bool = False) -> tuple[float, str]:
    path = Path(SESSION_BASELINE_FILE)
    now_utc = datetime.now(timezone.utc)
    if reset:
        data = _write_session_baseline(path, current_total, now_utc)
        return float(data["session_start_total"]), str(data["session_started_at"])
    existing = _read_session_baseline(path)
    if isinstance(existing, dict):
        try:
            return float(existing["session_start_total"]), str(existing["session_started_at"])
        except Exception:
            pass
    data = _write_session_baseline(path, current_total, now_utc)
    return float(data["session_start_total"]), str(data["session_started_at"])


def resolve_24h_baseline(current_total: float) -> float | None:
    csv_path = Path(PORTFOLIO_HISTORY_FILE)
    if not csv_path.is_file():
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    best_before_cutoff: float | None = None
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    total = float(row.get("total_value", ""))
                except Exception:
                    continue
                if ts <= cutoff:
                    best_before_cutoff = total
    except Exception:
        return None
    if best_before_cutoff is None:
        return None
    return float(best_before_cutoff)


def print_report(*, reset_session: bool = False) -> int:
    bal = get_current_balance()

    print("═══════════════════════════════════════════════")
    print("           NANOC LAW PnL REPORT (FIXED v4)")
    print("═══════════════════════════════════════════════")

    if not bal:
        print("No valid balance found.")
        print()
        print("📈 RECENT TRADES (last 8)")
        print("═══════════════════════════════════════════════")
        for t in get_recent_trades():
            print(t)
        print("═══════════════════════════════════════════════")
        return 0

    total = float(bal["total"])
    print(f"💰 CURRENT BALANCE  (source: {bal['source']})")
    print(f"   USDC:   ${bal['usdc']:.2f}")
    print(f"   WMATIC: ${bal['wmatic']:.2f}")
    print(f"   USDT:   ${bal['usdt']:.2f}")
    print(f"   TOTAL:  ${total:.2f}")
    print()

    baseline_total = float(resolve_portfolio_baseline_usd(total))
    baseline_delta = total - baseline_total
    baseline_pct = _pct_change(total, baseline_total)

    session_total, session_started_at = resolve_session_baseline(total, reset=reset_session)
    session_delta = total - session_total
    session_pct = _pct_change(total, session_total)

    baseline_24h = resolve_24h_baseline(total)
    if baseline_24h is not None:
        pnl_24h = total - baseline_24h
        pct_24h = _pct_change(total, baseline_24h)
        pnl_24h_line = f"24h PnL:      ${pnl_24h:+.2f} ({pct_24h:+.2f}%)"
    else:
        pnl_24h_line = "24h PnL:      n/a (need >=24h history in portfolio_history.csv)"

    print("📊 PNL SNAPSHOT")
    print(f"Since baseline: ${baseline_delta:+.2f} ({baseline_pct:+.2f}%)")
    print(f"Session PnL:   ${session_delta:+.2f} ({session_pct:+.2f}%)")
    print(f"Session start: {session_started_at}")
    print(pnl_24h_line)
    print("Reset session baseline: nanopnl --reset-session")
    print()

    recent = get_recent_trades()
    print("📈 RECENT TRADES (last 8)")
    print("═══════════════════════════════════════════════")
    for t in recent:
        print(t)
    print("═══════════════════════════════════════════════")
    if recent:
        print(f"🧾 LAST TRADE HINT: {recent[-1]}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nanoclaw PnL report")
    parser.add_argument("--reset-session", action="store_true", help="Reset session baseline to current total")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    return print_report(reset_session=bool(args.reset_session))


if __name__ == "__main__":
    raise SystemExit(main())
