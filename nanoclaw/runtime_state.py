"""User-controlled runtime state (``control.json``) — never managed by git or env sync."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# Live file read by nanoclaw each cycle (``external_layer.control.load_cycle_control``).
CONTROL_JSON_FILENAME = "control.json"

# Committed template only — nanoup may copy this to ``control.json`` when no snapshot exists.
CONTROL_JSON_EXAMPLE_FILENAME = "control.json.example"

# Persistent operator snapshot (gitignored). Survives ``git pull`` deleting the live file.
RUNTIME_STATE_DIRNAME = ".runtime"
CONTROL_JSON_BACKUP_FILENAME = "control.json.bak"

# When true in ``control.json``, external layer must not overwrite ``paused`` from risk tiers.
OPERATOR_PAUSE_LOCK_KEY = "operator_pause_lock"

NANOUP_PRESERVE_RUNTIME_FILES: tuple[str, ...] = (CONTROL_JSON_FILENAME,)


def repo_paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = (repo_root or Path.cwd()).resolve()
    runtime_dir = root / RUNTIME_STATE_DIRNAME
    return {
        "root": root,
        "runtime_dir": runtime_dir,
        "control": root / CONTROL_JSON_FILENAME,
        "example": root / CONTROL_JSON_EXAMPLE_FILENAME,
        "backup": runtime_dir / CONTROL_JSON_BACKUP_FILENAME,
    }


def snapshot_control_json(repo_root: Path | None = None) -> bool:
    """Copy live ``control.json`` to ``.runtime/control.json.bak`` when present."""
    paths = repo_paths(repo_root)
    live = paths["control"]
    if not live.is_file():
        return False
    paths["runtime_dir"].mkdir(parents=True, exist_ok=True)
    shutil.copy2(live, paths["backup"])
    return True


def restore_control_json(repo_root: Path | None = None) -> str:
    """Restore live ``control.json`` after git operations.

    Prefers ``.runtime/control.json.bak`` over whatever ``git pull`` left on disk.

    Returns: ``restored`` | ``seeded`` | ``unchanged`` | ``missing``.
    """
    paths = repo_paths(repo_root)
    live = paths["control"]
    backup = paths["backup"]
    example = paths["example"]

    if backup.is_file():
        paths["runtime_dir"].mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, live)
        return "restored"

    if live.is_file():
        snapshot_control_json(repo_root)
        return "unchanged"

    if example.is_file():
        paths["runtime_dir"].mkdir(parents=True, exist_ok=True)
        shutil.copy2(example, live)
        shutil.copy2(live, backup)
        return "seeded"

    return "missing"


def ensure_control_json_before_git(repo_root: Path | None = None) -> None:
    """Nanoup: snapshot operator ``control.json`` before fetch/pull/stash."""
    snapshot_control_json(repo_root)


def ensure_control_json_after_git(repo_root: Path | None = None) -> str:
    """Nanoup: restore or seed ``control.json`` after fetch/pull/stash (always run)."""
    return restore_control_json(repo_root)
