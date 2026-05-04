#!/usr/bin/env python3
# ruff: noqa: E402
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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanoclaw.env_sync import ENV_SYNC_EXCLUDED_KEYS, sanitize_env_content


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
    out = sanitize_env_content(text)
    if args.write:
        args.output.write_text(out, encoding="utf-8")
        print(
            f"wrote {args.output} — review: git diff {args.output} "
            f"(excluded keys: {', '.join(ENV_SYNC_EXCLUDED_KEYS)})",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
