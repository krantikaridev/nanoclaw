#!/usr/bin/env python3
"""Verify env/template consistency and config coverage."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanoclaw.env_sync import ENV_SYNC_EXCLUDED_KEYS, compute_env_sync_diff

CONFIG_PATH = REPO_ROOT / "config.py"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
ENV_PATH = REPO_ROOT / ".env"

ENV_KEY_PATTERN = re.compile(r'^([A-Z][A-Z0-9_]*)=', re.MULTILINE)
CONFIG_KEY_PATTERNS = (
    re.compile(r'\benv_(?:str|int|float|bool)\(\s*"([A-Z0-9_]+)"'),
    re.compile(r'\bos\.getenv\(\s*"([A-Z0-9_]+)"'),
)


def extract_env_example_keys(content: str) -> set[str]:
    return set(ENV_KEY_PATTERN.findall(content))


def extract_config_keys(content: str) -> set[str]:
    keys: set[str] = set()
    for pattern in CONFIG_KEY_PATTERNS:
        keys.update(pattern.findall(content))
    return keys


def main() -> int:
    env_example_content = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    config_content = CONFIG_PATH.read_text(encoding="utf-8")

    env_example_keys = extract_env_example_keys(env_example_content)
    config_keys = extract_config_keys(config_content)

    missing = sorted(config_keys - env_example_keys)
    if missing:
        print("ERROR: .env.example is missing keys used by config.py:")
        for key in missing:
            print(f"  - {key}")
        return 1

    print("OK: .env.example covers all config.py env keys.")

    if not ENV_PATH.exists():
        print("INFO: .env not found; skipping .env -> .env.example drift check.")
        return 0

    env_content = ENV_PATH.read_text(encoding="utf-8")
    diff = compute_env_sync_diff(env_content, env_example_content)
    if diff.missing_in_example:
        print("ERROR: .env.example is missing keys that exist in .env:")
        for key in diff.missing_in_example:
            print(f"  - {key}")
    if diff.extra_in_example:
        print("ERROR: .env.example has extra keys not present in .env:")
        for key in diff.extra_in_example:
            print(f"  - {key}")
    if diff.content_mismatch:
        print(
            "ERROR: .env.example content drift detected vs sanitized .env "
            f"(excluded value keys: {', '.join(ENV_SYNC_EXCLUDED_KEYS)})."
        )
        print("Run: python scripts/nanoenv_example.py --write")

    if diff.missing_in_example or diff.extra_in_example or diff.content_mismatch:
        return 1

    print("OK: .env.example is in sync with sanitized .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
