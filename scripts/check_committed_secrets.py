#!/usr/bin/env python3
# ruff: noqa: E402
"""
Guardrail: fail if tracked/staged content looks like committed secrets.

- Blocks committing raw env files (.env, .env.<profile>, etc.) except *.example / *.sample.
- Blocks KEY=value lines for known secret keys when the value is non-placeholder.

Used by .githooks/pre-commit and CI (see .github/workflows/ci.yml).
Enable the hook: from repo root, run:  git config core.hooksPath .githooks
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanoclaw.env_sync import ENV_SYNC_EXCLUDED_KEYS

# Env-style assignments for these keys must not carry real-looking values.
_SECRET_ASSIGN_KEYS = frozenset(ENV_SYNC_EXCLUDED_KEYS)

_PLACEHOLDER_FROZEN = frozenset(
    {
        "",
        "...",
        "xxx",
        "changeme",
        "placeholder",
        "your_key_here",
        "replace_me",
    }
)

_ENV_ASSIGN_RE = re.compile(r"^(?:export\s+)?(?P<key>[A-Z][A-Z0-9_]*)\s*=\s*(?P<val>.*)$")


def _is_placeholder(val: str) -> bool:
    v = val.strip().strip('"').strip("'")
    if not v:
        return True
    if v.lower() in _PLACEHOLDER_FROZEN:
        return True
    if v.startswith("${") or v.startswith("$("):
        return True
    if v.startswith("<") and v.endswith(">"):
        return True
    return False


def _looks_like_secret_value(val: str) -> bool:
    if _is_placeholder(val):
        return False
    v = val.strip().strip('"').strip("'")
    # Ethereum-style hex keys / long secrets
    if re.fullmatch(r"0x[a-fA-F0-9]{64}", v):
        return True
    if len(v) >= 24 and re.match(r"^[A-Za-z0-9+/=_-]+$", v):
        return True
    # Telegram bot token shape
    if re.fullmatch(r"\d{8,}:[A-Za-z0-9_-]{30,}", v):
        return True
    return False


def _forbidden_env_path(rel_path: str) -> bool:
    """Return True if this path must not be committed (raw env / secrets file)."""
    name = PurePosixPath(rel_path.replace("\\", "/")).name
    if name == ".env" or name == ".env.local":
        return True
    if name.startswith(".env.") and (
        name.endswith(".example") or name.endswith(".sample")
    ):
        return False
    if name.startswith(".env."):
        return True
    return False


def _check_line_text(line: str, *, path_label: str, errors: list[str]) -> None:
    s = line.rstrip("\n\r")
    if not s.strip() or s.lstrip().startswith("#"):
        return
    m = _ENV_ASSIGN_RE.match(s.strip())
    if not m:
        return
    key = m.group("key")
    if key not in _SECRET_ASSIGN_KEYS:
        return
    val = m.group("val") or ""
    if _looks_like_secret_value(val):
        errors.append(f"{path_label}: blocked assignment for {key} (non-placeholder value)")


def _git_output(args: list[str]) -> str:
    r = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    if r.returncode != 0:
        return ""
    return r.stdout


def scan_staged_git_diff(errors: list[str]) -> None:
    """Inspect staged changes only (pre-commit)."""
    names = _git_output(["diff", "--cached", "--name-only", "--diff-filter=ACM"]).splitlines()
    for raw in names:
        path = raw.strip()
        if not path:
            continue
        if _forbidden_env_path(path):
            errors.append(f"blocked path staged for commit: {path} (use .env.example / docs; never commit live .env)")

    diff = _git_output(["diff", "--cached", "--no-color", "-U0"])
    current_file = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            part = line[4:].strip()
            if part.startswith("b/"):
                part = part[2:]
            current_file = part
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        # Skip diff hunks / empty adds
        _check_line_text(body, path_label=f"staged:{current_file}", errors=errors)


def scan_all_tracked_files(errors: list[str]) -> None:
    """Inspect working tree content for tracked files (CI after checkout)."""
    root = REPO_ROOT
    listing = _git_output(["ls-files"])
    for raw in listing.splitlines():
        rel = raw.strip()
        if not rel:
            continue
        if _forbidden_env_path(rel):
            errors.append(f"tracked file forbidden: {rel}")
            continue
        p = root / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            _check_line_text(line, path_label=rel, errors=errors)


def main() -> int:
    p = argparse.ArgumentParser(description="Reject commits that include obvious secrets.")
    p.add_argument(
        "--staged",
        action="store_true",
        help="Check git staged diff only (pre-commit).",
    )
    p.add_argument(
        "--all-tracked",
        action="store_true",
        help="Check all git-tracked files (CI).",
    )
    args = p.parse_args()

    errors: list[str] = []
    if args.staged:
        scan_staged_git_diff(errors)
    elif args.all_tracked:
        scan_all_tracked_files(errors)
    else:
        p.error("specify --staged or --all-tracked")

    if errors:
        print("check_committed_secrets: FAILED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
