"""Runtime state paths and control.json preservation across nanoup."""

from __future__ import annotations

import json
from pathlib import Path

from nanoclaw.runtime_state import (
    CONTROL_JSON_FILENAME,
    NANOUP_PRESERVE_RUNTIME_FILES,
    OPERATOR_PAUSE_LOCK_KEY,
    ensure_control_json_after_git,
    ensure_control_json_before_git,
    repo_paths,
    snapshot_control_json,
)


def test_control_json_listed_for_nanoup_preservation():
    assert CONTROL_JSON_FILENAME == "control.json"
    assert CONTROL_JSON_FILENAME in NANOUP_PRESERVE_RUNTIME_FILES


def test_restore_control_json_after_simulated_git_delete(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    paths = repo_paths(root)
    paths["runtime_dir"].mkdir(parents=True)
    live = paths["control"]
    backup = paths["backup"]

    live.write_text(
        json.dumps({"paused": False, OPERATOR_PAUSE_LOCK_KEY: True}) + "\n",
        encoding="utf-8",
    )
    ensure_control_json_before_git(root)
    assert backup.is_file()

    live.unlink()
    assert not live.exists()

    status = ensure_control_json_after_git(root)
    assert status == "restored"
    data = json.loads(live.read_text(encoding="utf-8"))
    assert data["paused"] is False
    assert data[OPERATOR_PAUSE_LOCK_KEY] is True


def test_seed_control_json_from_example_when_missing(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    paths = repo_paths(root)
    paths["example"].write_text(
        json.dumps({"paused": False, OPERATOR_PAUSE_LOCK_KEY: False}) + "\n",
        encoding="utf-8",
    )

    status = ensure_control_json_after_git(root)
    assert status == "seeded"
    assert paths["control"].is_file()
    assert paths["backup"].is_file()


def test_snapshot_control_json_noop_when_missing(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    assert snapshot_control_json(root) is False
