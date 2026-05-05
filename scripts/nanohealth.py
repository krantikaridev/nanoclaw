#!/usr/bin/env python3
"""Exit 0 if Polygon PoS JSON-RPC is reachable (chain 137); non-zero otherwise.

Used standalone (`nanohealth`) and from `nanoup` after the bot starts.
Loads `.env` from repo root (same as other runtime scripts).
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

    parser = argparse.ArgumentParser(description="Check Polygon PoS RPC health (connect + chain 137).")
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-endpoint HTTP timeout seconds (default: 30).",
    )
    args = parser.parse_args(argv)

    import config  # noqa: F401 — load_dotenv via repo config

    from nanoclaw.rpc_health import check_polygon_pos_rpc

    ok, msg = check_polygon_pos_rpc(timeout=int(args.timeout))
    if ok:
        print(f"nanohealth: {msg}")
        return 0
    print(f"nanohealth: UNHEALTHY — {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
