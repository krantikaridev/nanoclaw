#!/usr/bin/env python3
"""Adverse-window PnL attribution (read-only): mark vs churn vs trade est."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nanoclaw.pnl_adverse_day import (  # noqa: E402
    build_adverse_day_report,
    format_adverse_day_oneliner,
    pnl_adverse_day_window_hours,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Adverse-day read-only metrics (TOTAL Δ < 0 over window)"
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Lookback hours (default: PNL_ADVERSE_DAY_WINDOW_HOURS or 24)",
    )
    parser.add_argument(
        "--log",
        default="real_cron.log",
        help="Cron log path (default: real_cron.log)",
    )
    parser.add_argument(
        "--portfolio-history",
        default="portfolio_history.csv",
        help="Portfolio history CSV (default: portfolio_history.csv)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    hours = float(args.hours) if args.hours is not None else pnl_adverse_day_window_hours()
    _metrics, lines = build_adverse_day_report(
        window_hours=hours,
        log_path=args.log,
        portfolio_history_path=args.portfolio_history,
    )
    for line in lines:
        print(line)
    if _metrics is not None:
        one = format_adverse_day_oneliner(_metrics)
        if one:
            print(one)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
