#!/usr/bin/env python3
"""Sync on-chain USDT/USDC transfer tags into ``.runtime/pnl_flow_events.jsonl``.

Usage:
  python scripts/pnl_flow_sync.py
  python scripts/pnl_flow_sync.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    parser = argparse.ArgumentParser(
        description="Scrape Polygon ERC-20 Transfer logs for stage-wallet capital flows."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scraped flows without writing jsonl.",
    )
    parser.add_argument(
        "--lookback-hours",
        type=float,
        default=None,
        help="Override PNL_FLOW_ONCHAIN_LOOKBACK_HOURS.",
    )
    args = parser.parse_args(argv)

    import config  # noqa: F401 — load_dotenv

    from nanoclaw.opex_runway import format_wallet_short
    from nanoclaw.pnl_flow_onchain import (
        PNL_FLOW_EVENTS_FILE,
        pnl_flow_onchain_enabled,
        pnl_flow_wallet,
        run_pnl_flow_sync,
    )

    if not pnl_flow_onchain_enabled():
        print("[pnl_flow_sync] PNL_FLOW_ONCHAIN_ENABLED=false — skip")
        return 0

    wallet = pnl_flow_wallet()
    if not wallet:
        print("[pnl_flow_sync] PNL_FLOW_WALLET / WALLET unset — skip", file=sys.stderr)
        return 1

    result = run_pnl_flow_sync(
        lookback_hours=args.lookback_hours,
        dry_run=args.dry_run,
    )
    if result is None:
        print("[pnl_flow_sync] sync skipped — check PNL_FLOW_ONCHAIN_ENABLED / wallet", file=sys.stderr)
        return 1

    if args.dry_run:
        print(
            f"[pnl_flow_sync] dry-run wallet={wallet} flows={result.scraped}"
        )
        for rec in result.records:
            print(
                f"  {rec.kind} ${rec.amount_usd:.2f} @ {rec.ts.isoformat()} "
                f"tx={rec.tx_hash} token={rec.token_symbol}"
            )
        return 0

    wallet_short = format_wallet_short(result.wallet)
    print(
        f"[nanoclaw] PNL_FLOW_SYNC | scraped={result.scraped} appended={result.appended} "
        f"wallet={wallet_short} path={PNL_FLOW_EVENTS_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
