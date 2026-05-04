#!/usr/bin/env python3
"""Generate a clean PnL report from real_cron.log snapshots."""

from __future__ import annotations

import argparse
import re
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

WALLET_BALANCE_RE = re.compile(r"WALLET BALANCE\s+\|\s+USDC=\$?([0-9]+(?:\.[0-9]+)?)")
REAL_BALANCE_RE = re.compile(
    r"Real USDT:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*USDC:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*WMATIC:\s*([0-9]+(?:\.[0-9]+)?)"
)

TIMESTAMP_PATTERNS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
)


@dataclass
class BalanceSnapshot:
    timestamp: datetime
    usdt: float
    usdc: float
    wmatic: float
    source: str
    line_no: int

    @property
    def total(self) -> float:
        return self.usdt + self.usdc + self.wmatic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate live PnL report from real_cron.log")
    parser.add_argument(
        "--log-file",
        default="real_cron.log",
        help="Path to log file (default: real_cron.log)",
    )
    return parser.parse_args()


def extract_timestamp(line: str, fallback: datetime) -> datetime:
    # Match either bracketed or plain timestamp prefixes.
    candidates = re.findall(r"(?:\[(.*?)\]|(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?))", line)
    for candidate in candidates:
        text = (candidate[0] or candidate[1]).strip()
        if not text:
            continue
        for pattern in TIMESTAMP_PATTERNS:
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue

    # Handle syslog-like format: "May 04 13:42:10 ..."
    syslog_match = re.search(r"\b([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b", line)
    if syslog_match:
        try:
            parsed = datetime.strptime(syslog_match.group(1), "%b %d %H:%M:%S")
            return parsed.replace(year=fallback.year)
        except ValueError:
            pass

    return fallback


def extract_snapshots(log_path: Path) -> list[BalanceSnapshot]:
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    now = datetime.now()
    pending_wallet: tuple[int, datetime, float] | None = None
    snapshots: list[BalanceSnapshot] = []

    for line_no, line in enumerate(lines, start=1):
        # A wallet line is only eligible to pair with a real-balance line
        # within the next 6 lines. Once stale, clear it to avoid orphan
        # snapshots that can distort chronological PnL baselines.
        if pending_wallet and (line_no - pending_wallet[0]) > 6:
            pending_wallet = None

        timestamp = extract_timestamp(line, now)
        wallet_match = WALLET_BALANCE_RE.search(line)
        real_match = REAL_BALANCE_RE.search(line)

        if wallet_match:
            pending_wallet = (line_no, timestamp, float(wallet_match.group(1)))
            continue

        if not real_match:
            continue

        usdt = float(real_match.group(1))
        usdc = float(real_match.group(2))
        wmatic = float(real_match.group(3))

        if pending_wallet and (line_no - pending_wallet[0]) <= 6:
            _, pending_ts, pending_usdc = pending_wallet
            pending_wallet = None
            snapshots.append(
                BalanceSnapshot(
                    timestamp=pending_ts,
                    usdt=usdt,
                    usdc=pending_usdc if pending_usdc > 0 else usdc,
                    wmatic=wmatic,
                    source="paired",
                    line_no=line_no,
                )
            )
        else:
            snapshots.append(
                BalanceSnapshot(
                    timestamp=timestamp,
                    usdt=usdt,
                    usdc=usdc,
                    wmatic=wmatic,
                    source="real",
                    line_no=line_no,
                )
            )

    # Do not emit orphan wallet-only snapshots. They are incomplete portfolio
    # states (USDT/WMATIC unknown) and can skew PnL baselines.

    snapshots.sort(key=lambda snap: (snap.timestamp, snap.line_no))
    return snapshots


def pnl(current: BalanceSnapshot, baseline: BalanceSnapshot) -> tuple[float, float]:
    delta = current.total - baseline.total
    pct = (delta / baseline.total * 100.0) if baseline.total > 0 else 0.0
    return delta, pct


def baseline_for_today(snapshots: Iterable[BalanceSnapshot], today: datetime) -> BalanceSnapshot | None:
    same_day = [snap for snap in snapshots if snap.timestamp.date() == today.date()]
    if same_day:
        return same_day[0]
    return None


def nearest_snapshot_before(
    snapshots: list[BalanceSnapshot], ordered_times: list[datetime], target: datetime
) -> BalanceSnapshot | None:
    idx = bisect_right(ordered_times, target) - 1
    if idx < 0:
        return None
    return snapshots[idx]


def format_window_rows(
    snapshots: list[BalanceSnapshot], current: BalanceSnapshot, step_hours: int, windows: int
) -> list[str]:
    ordered_times = [snap.timestamp for snap in snapshots]
    rows: list[str] = []

    for window in range(1, windows + 1):
        hours = step_hours * window
        ref_time = current.timestamp - timedelta(hours=hours)
        baseline = nearest_snapshot_before(snapshots, ordered_times, ref_time)
        if baseline is None:
            rows.append(f"  - {hours:>2}h ago: n/a")
            continue
        delta, pct = pnl(current, baseline)
        rows.append(
            f"  - {hours:>2}h ago: {delta:+8.2f} USD ({pct:+6.2f}%) | baseline={baseline.total:8.2f}"
        )

    return rows


def print_report(log_file: str) -> int:
    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = Path(__file__).resolve().parents[1] / log_path

    if not log_path.exists():
        print("NANOCLAW PnL REPORT")
        print("=" * 72)
        print(f"Log file not found: {log_path}")
        return 1

    snapshots = extract_snapshots(log_path)
    if not snapshots:
        print("NANOCLAW PnL REPORT")
        print("=" * 72)
        print(f"No balance snapshots found in {log_path}")
        return 1

    current = snapshots[-1]
    day_baseline = baseline_for_today(snapshots, current.timestamp) or snapshots[0]
    day_delta, day_pct = pnl(current, day_baseline)

    print("NANOCLAW PnL REPORT")
    print("=" * 72)
    print(f"Log File          : {log_path}")
    print(f"Snapshots Parsed  : {len(snapshots)}")
    print(f"Current Timestamp : {current.timestamp:%Y-%m-%d %H:%M:%S}")
    print("-" * 72)
    print("Current Balances")
    print(f"  USDC            : {current.usdc:10.2f}")
    print(f"  WMATIC          : {current.wmatic:10.2f}")
    print(f"  USDT            : {current.usdt:10.2f}")
    print(f"  TOTAL           : {current.total:10.2f}")
    print("-" * 72)
    print("Today PnL")
    print(f"  Baseline Time   : {day_baseline.timestamp:%Y-%m-%d %H:%M:%S}")
    print(f"  Baseline Total  : {day_baseline.total:10.2f}")
    print(f"  PnL             : {day_delta:+10.2f} USD ({day_pct:+.2f}%)")
    print("-" * 72)
    print("Last 6 x 4-hour windows (rolling from current)")
    for row in format_window_rows(snapshots, current, step_hours=4, windows=6):
        print(row)
    print("-" * 72)
    print("Last 4 x 6-hour windows (rolling from current)")
    for row in format_window_rows(snapshots, current, step_hours=6, windows=4):
        print(row)

    return 0


def main() -> int:
    args = parse_args()
    return print_report(args.log_file)


if __name__ == "__main__":
    raise SystemExit(main())
