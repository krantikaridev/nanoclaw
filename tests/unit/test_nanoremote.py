"""Tests for scripts/nanoremote.sh — remote SSH operator wrapper."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "nanoremote.sh"
CONFIG_EXAMPLE = REPO_ROOT / "infra" / "config.yaml.example"


def _bash_executable() -> str | None:
    candidates: list[str] = []
    if shutil.which("bash"):
        candidates.append("bash")
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.is_file():
        candidates.append(str(git_bash))
    for candidate in candidates:
        probe = subprocess.run(
            [candidate, "-lc", "echo ok"],
            text=True,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return candidate
    return None


def _require_bash() -> str:
    bash = _bash_executable()
    if bash is None:
        pytest.skip("bash not available or not runnable in this environment")
    return bash


def _run_nanoremote(bash: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [bash, str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def test_nanoremote_script_exists() -> None:
    assert SCRIPT_PATH.is_file()
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    for token in ("logs", "nano8h", "nano12h", "diag", "shell", "--role", "--host", "--key", "--dry-run"):
        assert token in text


def test_config_yaml_example_has_required_keys() -> None:
    assert CONFIG_EXAMPLE.is_file()
    text = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    for key in ("stage_host", "dev_host", "ssh_key", "ssh_user", "remote_root"):
        assert f"{key}:" in text


def test_nanoremote_help_exits_zero() -> None:
    bash = _require_bash()
    result = _run_nanoremote(bash, "--help")
    assert result.returncode == 0
    assert "nano12h" in result.stdout
    assert "diag" in result.stdout


def test_nanoremote_requires_host_when_no_config(tmp_path: Path) -> None:
    bash = _require_bash()
    missing_config = tmp_path / "missing.yaml"
    result = _run_nanoremote(bash, "--config", str(missing_config), "logs")
    assert result.returncode != 0
    combined = ((result.stdout or "") + (result.stderr or "")).lower()
    assert "no host" in combined


def test_nanoremote_dry_run_nano12h_uses_green_gate(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text(
        "ssh_user: ubuntu\nstage_host: 10.0.0.2\nremote_root: ~/.nanobot/workspace/nanoclaw\n",
        encoding="utf-8",
    )
    result = _run_nanoremote(
        bash,
        "--config",
        str(config),
        "--role",
        "stage",
        "--dry-run",
        "nano12h",
    )
    assert result.returncode == 0, result.stderr
    assert "scripts/nano_green.sh --hours 12" in result.stdout
    assert ".venv/bin/activate" in result.stdout
    assert "clean_swap.py" in result.stdout


def test_nanoremote_dry_run_nano8h_hours(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text("ssh_user: ubuntu\nstage_host: 10.0.0.2\n", encoding="utf-8")
    result = _run_nanoremote(
        bash,
        "--config",
        str(config),
        "--host",
        "10.0.0.2",
        "--dry-run",
        "nano8h",
    )
    assert result.returncode == 0, result.stderr
    assert "scripts/nano_green.sh --hours 8" in result.stdout


def test_nanoremote_dry_run_diag_invokes_nanodiag(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text("ssh_user: ubuntu\nstage_host: 10.0.0.3\n", encoding="utf-8")
    result = _run_nanoremote(
        bash,
        "--config",
        str(config),
        "--host",
        "10.0.0.3",
        "--dry-run",
        "diag",
    )
    assert result.returncode == 0, result.stderr
    assert "scripts/nanodiag.sh" in result.stdout


def test_nanoremote_dry_run_logs_tail(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text("ssh_user: ubuntu\nstage_host: 10.0.0.4\n", encoding="utf-8")
    result = _run_nanoremote(
        bash,
        "--config",
        str(config),
        "--role",
        "stage",
        "--lines",
        "25",
        "--dry-run",
        "logs",
    )
    assert result.returncode == 0, result.stderr
    assert "tail -n 25 real_cron.log" in result.stdout


def test_nanoremote_dry_run_logs_follow(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text("ssh_user: ubuntu\nstage_host: 10.0.0.5\n", encoding="utf-8")
    result = _run_nanoremote(
        bash,
        "--config",
        str(config),
        "--role",
        "stage",
        "--follow",
        "--dry-run",
        "logs",
    )
    assert result.returncode == 0, result.stderr
    assert "tail -f real_cron.log" in result.stdout
