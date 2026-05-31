#!/usr/bin/env python3
"""Probe each configured Polygon RPC endpoint; exit 1 when all fail.

Usage:
  python scripts/rpc_probe.py
  python scripts/rpc_probe.py --alert   # Telegram when all endpoints fail (if configured)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _maybe_telegram_alert(text: str) -> None:
    try:
        from modules.agent_layer import _telegram_send_html
    except Exception:
        return
    try:
        _telegram_send_html(text)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    parser = argparse.ArgumentParser(description="Probe each Polygon RPC endpoint in config.")
    parser.add_argument("--timeout", type=int, default=12, help="Per-endpoint timeout seconds.")
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Send Telegram alert when zero endpoints are healthy (requires TELEGRAM_* in .env).",
    )
    args = parser.parse_args(argv)

    import config  # noqa: F401 — load_dotenv

    from nanoclaw.rpc_probe import (
        any_endpoint_healthy,
        format_probe_report,
        probe_configured_endpoints,
    )

    probes = probe_configured_endpoints(timeout=int(args.timeout))
    report = format_probe_report(probes)
    print(report)
    if any_endpoint_healthy(probes):
        return 0
    if args.alert:
        _maybe_telegram_alert(f"<b>nanoclaw RPC ALERT</b>\n<pre>{report}</pre>")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
