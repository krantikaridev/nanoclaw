#!/usr/bin/env python3
"""Preserve operator ``control.json`` across nanoup git operations (never env sync)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanoclaw.runtime_state import (  # noqa: E402
    ensure_control_json_after_git,
    ensure_control_json_before_git,
    snapshot_control_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup/restore control.json for nanoup.")
    parser.add_argument(
        "phase",
        choices=("before-git", "after-git", "snapshot"),
        help="before-git: snapshot to .runtime/; after-git: restore live file; snapshot: backup only",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    root = args.repo_root.resolve()

    if args.phase == "before-git":
        ensure_control_json_before_git(root)
        if snapshot_control_json(root):
            print("[nanoclaw] control.json snapshot saved to .runtime/control.json.bak")
        else:
            print("[nanoclaw] control.json not present — will restore from .runtime/ or example after git")
        return 0

    if args.phase == "snapshot":
        return 0 if snapshot_control_json(root) else 1

    status = ensure_control_json_after_git(root)
    if status == "restored":
        print("[nanoclaw] control.json restored from operator snapshot (.runtime/control.json.bak)")
    elif status == "seeded":
        print(
            "[nanoclaw] control.json created from control.json.example "
            "(set paused/operator_pause_lock as needed)"
        )
    elif status == "unchanged":
        print("[nanoclaw] control.json left in place")
    else:
        print(
            "[nanoclaw] WARNING: control.json missing and no backup/example — "
            "bot uses paused=false until you create control.json",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
