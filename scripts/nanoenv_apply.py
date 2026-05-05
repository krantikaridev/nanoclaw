#!/usr/bin/env python3
# ruff: noqa: E402
"""
Apply `.env.example` onto `.env` while preserving secret values from the existing `.env`.

Usage:
  python scripts/nanoenv_apply.py --write
  python scripts/nanoenv_apply.py --write --keep-extra-keys
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanoclaw.env_sync import ENV_SYNC_EXCLUDED_KEYS, merge_env_from_example


def _default_preserve_keys() -> tuple[str, ...]:
    # Preserve secrets by default, plus Telegram chat id commonly treated as runtime-specific.
    return (*ENV_SYNC_EXCLUDED_KEYS, "TELEGRAM_CHAT_ID")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply .env.example to .env while preserving selected values from existing .env."
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Target env file (default: .env)")
    parser.add_argument(
        "--template-file",
        type=Path,
        default=Path(".env.example"),
        help="Template file source (default: .env.example)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write merged output to --env-file (otherwise print to stdout).",
    )
    parser.add_argument(
        "--keep-extra-keys",
        action="store_true",
        help="Append keys present in existing .env but missing from template.",
    )
    parser.add_argument(
        "--preserve-key",
        action="append",
        default=[],
        help="Additional key to preserve from current .env (repeatable).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create timestamp backup of target .env before writing.",
    )
    args = parser.parse_args()

    template_path = args.template_file
    env_path = args.env_file
    if not template_path.is_file():
        print(f"error: template file not found: {template_path}", file=sys.stderr)
        return 2

    existing_env = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    template_env = template_path.read_text(encoding="utf-8")
    preserve_keys = tuple(_default_preserve_keys()) + tuple(str(x).strip() for x in args.preserve_key if str(x).strip())
    merged = merge_env_from_example(
        existing_env,
        template_env,
        preserve_keys=preserve_keys,
        keep_extra_keys=bool(args.keep_extra_keys),
    )

    if not args.write:
        sys.stdout.write(merged)
        return 0

    if env_path.exists() and not args.no_backup:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = env_path.with_name(f"{env_path.name}.bak.{stamp}")
        backup_path.write_text(existing_env, encoding="utf-8")
        print(f"backup created: {backup_path}", file=sys.stderr)

    env_path.write_text(merged, encoding="utf-8")
    print(
        f"wrote {env_path} from {template_path} (preserved keys: {', '.join(preserve_keys)})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
