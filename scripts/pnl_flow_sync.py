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
PNL_FLOW_EVENTS_FILE = ".runtime/pnl_flow_events.jsonl"


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

    from nanoclaw.pnl_flow_onchain import (
        merge_onchain_records_into_jsonl,
        pnl_flow_onchain_enabled,
        pnl_flow_wallet,
        scrape_onchain_flows,
    )

    if not pnl_flow_onchain_enabled():
        print("[pnl_flow_sync] PNL_FLOW_ONCHAIN_ENABLED=false — skip")
        return 0

    wallet = pnl_flow_wallet()
    if not wallet:
        print("[pnl_flow_sync] PNL_FLOW_WALLET / WALLET unset — skip", file=sys.stderr)
        return 1

    records = scrape_onchain_flows(
        wallet=wallet,
        lookback_hours=args.lookback_hours,
    )
    if args.dry_run:
        print(f"[pnl_flow_sync] dry-run wallet={wallet} flows={len(records)}")
        for rec in records:
            print(
                f"  {rec.kind} ${rec.amount_usd:.2f} @ {rec.ts.isoformat()} "
                f"tx={rec.tx_hash} token={rec.token_symbol}"
            )
        return 0

    existing, appended = merge_onchain_records_into_jsonl(records, PNL_FLOW_EVENTS_FILE)
    print(
        f"[pnl_flow_sync] wallet={wallet} scraped={len(records)} "
        f"jsonl_existing={existing} appended={appended} path={PNL_FLOW_EVENTS_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
