#!/usr/bin/env python3
"""Alert when stage-wallet stables fall below opex runway threshold.

Usage:
  python scripts/opex_runway.py --dry-run
  python scripts/opex_runway.py --stables-usd 5.0 --dry-run
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
        description="Check wallet stable runway vs monthly opex burn (Polygon stage wallet)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print assessment only; do not send Telegram.",
    )
    parser.add_argument(
        "--stables-usd",
        type=float,
        default=None,
        help="Override stables USD (for tests / manual what-if).",
    )
    args = parser.parse_args(argv)

    import config  # noqa: F401 — load_dotenv

    from nanoclaw.opex_runway import run_opex_runway_check

    _assessment, code = run_opex_runway_check(
        stables_usd=args.stables_usd,
        dry_run=bool(args.dry_run),
    )
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
