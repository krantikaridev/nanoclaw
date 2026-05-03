#!/usr/bin/env python3
"""
Sanitize a live `.env` into shareable form (secrets blanked).

Usage (repo root, with `.venv` activated):
  python scripts/nanoenv_example.py              # print to stdout
  python scripts/nanoenv_example.py --write      # overwrite ./.env.example — ALWAYS git diff before commit

Operator alias (optional):  nanoenv () { python3 "${NANOCLAW_ROOT:-.}/scripts/nanoenv_example.py" "$@"; }

Does not remove sections; preserves order and comments from your `.env`. For a curated canonical template,
still maintain `.env.example` by hand and use this script only to catch missing keys from a VM `.env`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Keys that must never appear with values in committed examples.
_SECRET_KEYS_EXACT = frozenset(
    {
        "POLYGON_PRIVATE_KEY",
        "PRIVATE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "GROK_API_KEY",
        "XAI_API_KEY",
        "ONEINCH_API_KEY",
        "INCH_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    }
)


def _is_secret_key(key: str) -> bool:
    """Prefer under-redacting public RPC/address keys over stripping legitimate config."""
    k = key.strip()
    if k in _SECRET_KEYS_EXACT:
        return True
    ku = k.upper()
    if ku.endswith("_PRIVATE_KEY") or ku.endswith("_SECRET"):
        return True
    if ku.endswith("_API_KEY"):
        return True
    if "TELEGRAM" in ku and "TOKEN" in ku:
        return True
    if ku == "PRIVATE_KEY":
        return True
    return False


def _sanitize_line(line: str) -> str:
    raw = line.rstrip("\n")
    if not raw.strip() or raw.lstrip().startswith("#"):
        return raw
    m = re.match(r"^([^\s=#]+)\s*=\s*(.*)$", raw)
    if not m:
        return raw
    key, _val = m.group(1), m.group(2)
    if _is_secret_key(key):
        return f"{key}="
    return raw


def main() -> None:
    p = argparse.ArgumentParser(description="Redact secrets from .env for .env.example")
    p.add_argument("--env-file", type=Path, default=Path(".env"), help="Source env file (default: .env)")
    p.add_argument(
        "--write",
        action="store_true",
        help="Write to .env.example in current working directory (review diff before commit!)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(".env.example"),
        help="Output path when using --write (default: .env.example)",
    )
    args = p.parse_args()
    src = args.env_file
    if not src.is_file():
        print(f"error: {src} not found", file=sys.stderr)
        sys.exit(2)
    text = src.read_text(encoding="utf-8", errors="replace")
    out = "\n".join(_sanitize_line(ln) for ln in text.splitlines()) + "\n"
    if args.write:
        args.output.write_text(out, encoding="utf-8")
        print(f"wrote {args.output} — review: git diff {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
