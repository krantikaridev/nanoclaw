#!/usr/bin/env python3
# ruff: noqa: E402
"""
Pre-push guard: ensure `.env.example` is synced from `.env` (secrets redacted).

By default this blocks pushes when sanitized `.env` and `.env.example` drift.
Set `NANOCLAW_CONFIRM_ENV_SYNC_SKIP=1` to bypass intentionally for a push.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanoclaw.env_sync import ENV_SYNC_EXCLUDED_KEYS, compute_env_sync_diff


def _env_truthy(name: str) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def check_env_sync(env_path: Path, example_path: Path, *, allow_skip: bool) -> tuple[int, str]:
    if not env_path.exists():
        return 0, "INFO: .env not found; skipping env sync push gate."
    if not example_path.exists():
        return 1, f"ERROR: {example_path} not found; cannot validate env sync before push."

    env_content = env_path.read_text(encoding="utf-8")
    example_content = example_path.read_text(encoding="utf-8")
    diff = compute_env_sync_diff(env_content, example_content)

    has_drift = bool(diff.missing_in_example or diff.extra_in_example or diff.content_mismatch)
    if not has_drift:
        return 0, "OK: .env.example is synced with sanitized .env."

    if allow_skip:
        return (
            0,
            "WARN: env sync drift bypassed by NANOCLAW_CONFIRM_ENV_SYNC_SKIP=1 for this push.",
        )

    lines = ["ERROR: push blocked — .env.example is not synced with sanitized .env."]
    if diff.missing_in_example:
        lines.append("Missing in .env.example:")
        lines.extend(f"  - {key}" for key in diff.missing_in_example)
    if diff.extra_in_example:
        lines.append("Extra in .env.example:")
        lines.extend(f"  - {key}" for key in diff.extra_in_example)
    if diff.content_mismatch:
        lines.append(
            "Content mismatch detected (non-secret values drift). "
            f"Excluded secret keys: {', '.join(ENV_SYNC_EXCLUDED_KEYS)}"
        )
    lines.append("Run:")
    lines.append("  python scripts/nanoenv_example.py --write")
    lines.append("  python scripts/verify_env_example_keys.py")
    lines.append("If intentional for one push, confirm with:")
    lines.append("  NANOCLAW_CONFIRM_ENV_SYNC_SKIP=1 git push")
    return 1, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-push guard for .env -> .env.example sync.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Path to runtime env file.")
    parser.add_argument(
        "--example-file",
        type=Path,
        default=Path(".env.example"),
        help="Path to env template file.",
    )
    args = parser.parse_args()

    allow_skip = _env_truthy("NANOCLAW_CONFIRM_ENV_SYNC_SKIP")
    code, message = check_env_sync(args.env_file, args.example_file, allow_skip=allow_skip)
    target = sys.stderr if code else sys.stdout
    print(message, file=target)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
