"""Tests for dev infra scripts (P0b–P3) and deploy role guard."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.deploy_role_guard import STAGE_WALLET, check_deploy_role

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _run_script(bash: str, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [bash, str(REPO_ROOT / "scripts" / script), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


# --- deploy_role_guard.py ---


@pytest.mark.parametrize(
    ("role", "branch", "wallet", "ok"),
    [
        ("dev", "V2", "0xabc", False),
        ("stage", "V4-play", "0xabc", False),
        ("dev", "V4-play", STAGE_WALLET, False),
        ("dev", "V4-play", "0xdevwallet00000000000000000000000001", True),
        ("stage", "V2", STAGE_WALLET, True),
    ],
)
def test_check_deploy_role(role: str, branch: str, wallet: str, ok: bool) -> None:
    passed, msg = check_deploy_role(role=role, branch=branch, wallet=wallet)
    assert passed is ok
    if not ok:
        assert msg


def test_deploy_role_guard_cli_blocks_dev_on_v2(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "python",
            str(REPO_ROOT / "scripts" / "deploy_role_guard.py"),
            "--role",
            "dev",
            "--branch",
            "V2",
            "--wallet",
            "0x1",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "BLOCKED" in result.stderr


def test_deploy_role_guard_reads_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "NANOCLAW_ROLE=dev\nWALLET=0xdev\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "python",
            str(REPO_ROOT / "scripts" / "deploy_role_guard.py"),
            "--root",
            str(tmp_path),
            "--branch",
            "V4-play",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0


# --- script existence ---


def test_dev_scripts_exist() -> None:
    for name in (
        "dev_preflight.sh",
        "dev_bootstrap.sh",
        "dev_destroy.sh",
        "lib/operator_ssh.sh",
    ):
        path = REPO_ROOT / "scripts" / name
        assert path.is_file(), name


def test_env_dev_example_has_v4_keys() -> None:
    text = (REPO_ROOT / ".env.dev.example").read_text(encoding="utf-8")
    for key in (
        "NANOCLAW_ROLE=dev",
        "STAGE_SEED_USD=50",
        "PLAY_BUDGET_ENABLED=true",
        "EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW=true",
    ):
        assert key in text


def test_vm_roles_doc_exists() -> None:
    text = (REPO_ROOT / "docs" / "VM_ROLES.md").read_text(encoding="utf-8")
    assert "0x05eF" in text
    assert "V4-play" in text


def test_cloud_init_templates_exist() -> None:
    for name in ("generic.yaml", "oracle-ubuntu.yaml", "README.md"):
        assert (REPO_ROOT / "infra" / "cloud-init" / name).is_file()


# --- dry-run integration ---


def test_dev_bootstrap_dry_run(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text("ssh_user: ubuntu\ndev_host: 10.0.0.9\n", encoding="utf-8")
    result = _run_script(
        bash,
        "dev_bootstrap.sh",
        "--config",
        str(config),
        "--role",
        "dev",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "git clone" in result.stdout or "git pull" in result.stdout
    assert "STAGE_SEED_USD" in result.stdout
    assert "nanobot_aliases.sh --install" in result.stdout


def test_dev_destroy_dry_run_wipe(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text("ssh_user: ubuntu\ndev_host: 10.0.0.10\n", encoding="utf-8")
    result = _run_script(
        bash,
        "dev_destroy.sh",
        "--config",
        str(config),
        "--role",
        "dev",
        "--wipe",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "wipe" in result.stdout.lower()
    assert "crontab" in result.stdout.lower()


def test_dev_preflight_dry_run_skip_remote(tmp_path: Path) -> None:
    bash = _require_bash()
    config = tmp_path / "config.yaml"
    config.write_text("ssh_user: ubuntu\ndev_host: 10.0.0.11\n", encoding="utf-8")
    result = _run_script(
        bash,
        "dev_preflight.sh",
        "--config",
        str(config),
        "--role",
        "dev",
        "--dry-run",
        "--skip-remote",
    )
    assert result.returncode == 0, result.stderr
    assert "dev_preflight: PASS" in result.stdout


def test_nanodeploy_includes_role_guard() -> None:
    text = (REPO_ROOT / "scripts" / "nanodeploy.sh").read_text(encoding="utf-8")
    assert "deploy_role_guard.py" in text
    assert "role=" in text
