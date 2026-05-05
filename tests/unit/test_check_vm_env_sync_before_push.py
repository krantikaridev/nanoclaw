from __future__ import annotations

from pathlib import Path

from scripts.check_vm_env_sync_before_push import check_env_sync


def test_check_env_sync_skips_when_env_missing(tmp_path: Path):
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"
    example_file.write_text("A=1\n", encoding="utf-8")

    code, msg = check_env_sync(env_file, example_file, allow_skip=False)
    assert code == 0
    assert "skipping env sync push gate" in msg


def test_check_env_sync_passes_when_synced(tmp_path: Path):
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"
    env_file.write_text("POLYGON_PRIVATE_KEY=secret\nA=1\n", encoding="utf-8")
    example_file.write_text("POLYGON_PRIVATE_KEY=\nA=1\n", encoding="utf-8")

    code, msg = check_env_sync(env_file, example_file, allow_skip=False)
    assert code == 0
    assert "synced" in msg


def test_check_env_sync_blocks_on_drift_without_confirmation(tmp_path: Path):
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"
    env_file.write_text("A=2\n", encoding="utf-8")
    example_file.write_text("A=1\n", encoding="utf-8")

    code, msg = check_env_sync(env_file, example_file, allow_skip=False)
    assert code == 1
    assert "push blocked" in msg
    assert "nanoenv_example.py --write" in msg
    assert "NANOCLAW_CONFIRM_ENV_SYNC_SKIP=1 git push" in msg


def test_check_env_sync_allows_drift_with_confirmation(tmp_path: Path):
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"
    env_file.write_text("A=2\n", encoding="utf-8")
    example_file.write_text("A=1\n", encoding="utf-8")

    code, msg = check_env_sync(env_file, example_file, allow_skip=True)
    assert code == 0
    assert "bypassed" in msg
