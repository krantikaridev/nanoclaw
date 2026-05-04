#!/usr/bin/env python3
"""Verify .env.example includes all env keys referenced in config.py."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.py"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
