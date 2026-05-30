#!/usr/bin/env python3
"""Operator audit for copy-trade wallet list.

Usage:
  python scripts/copy_trading_audit.py
  nanocopyaudit   # after: source scripts/nanobot_aliases.sh

Exit codes:
  0 — ok (disabled, or ≥1 tradeable wallet)
  1 — COPY_TRADING_ENABLED but no tradeable wallets
  2 — every entry is a known Polygon token contract (legacy misconfig)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import config as cfg  # noqa: E402
from modules.copy_trading_audit import (  # noqa: E402
    CopyTradingAuditReport,
    audit_followed_wallets,
)

DEFAULT_CONFIG = REPO_ROOT / "followed_wallets.json"
EXAMPLE_CONFIG = REPO_ROOT / "followed_wallets.json.example"


def load_wallet_list(path: Path) -> list[str]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("wallets", []) if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return []
    return [str(w) for w in raw if w]


def run_audit(config_path: Path | None = None) -> CopyTradingAuditReport:
    path = config_path or DEFAULT_CONFIG
    wallets = load_wallet_list(path)
    return audit_followed_wallets(
        wallets,
        copy_trading_enabled=bool(cfg.COPY_TRADING_ENABLED),
        reject_token_contracts=bool(cfg.COPY_TRADING_REJECT_TOKEN_CONTRACTS),
    )


def main(argv: list[str] | None = None) -> int:
    config_path = DEFAULT_CONFIG
    args = list(argv or sys.argv[1:])
    if args and args[0] == "--config":
        config_path = Path(args[1]).resolve()
        args = args[2:]

    report = run_audit(config_path)
    print(f"=== copy trading audit | config={config_path} ===")
    for line in report.lines():
        print(line)

    if EXAMPLE_CONFIG.is_file() and config_path == DEFAULT_CONFIG:
        example_wallets = load_wallet_list(EXAMPLE_CONFIG)
        if example_wallets:
            print(f"example template has {len(example_wallets)} placeholder wallet(s)")

    perf = REPO_ROOT / str(cfg.COPY_WALLET_PERFORMANCE_FILE)
    if perf.is_file():
        print(f"wallet_performance: {perf} (review trades after wallet list is fixed)")

    return int(report.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
