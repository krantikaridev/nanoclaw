import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_nanobot_aliases_script_defines_core_functions():
    script_path = REPO_ROOT / "scripts" / "nanobot_aliases.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "nanoup()" in content
    assert "nanokill()" in content
    assert "nanostatus()" in content
    assert "nanopnl()" in content
    assert "nanorestart()" in content
    assert "nanodaily()" in content
    assert "nanobot()" in content
    assert "nanoattach()" in content


def test_nanobot_aliases_script_supports_install_mode():
    script_path = REPO_ROOT / "scripts" / "nanobot_aliases.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "--install" in content
    assert "source ~/.bashrc" in content
    # Guard against accidental legacy alias block duplication.
    assert content.count("#!/usr/bin/env bash") == 1
    assert 'alias nanoup=' not in content


def test_nanokill_and_nanorestart_scripts_exist():
    assert (REPO_ROOT / "scripts" / "nanokill.sh").is_file()
    assert (REPO_ROOT / "scripts" / "nanorestart.sh").is_file()


def test_nanodaily_exists_and_is_executable_in_git():
    script_path = REPO_ROOT / "nanodaily"
    assert script_path.is_file()

    tracked = subprocess.check_output(
        ["git", "ls-files", "--stage", "nanodaily"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    assert tracked.startswith("100755 "), tracked


def test_nanodaily_script_does_not_depend_on_shell_function_aliases():
    script_path = REPO_ROOT / "nanodaily"
    content = script_path.read_text(encoding="utf-8")

    assert "python scripts/pnl_report.py" in content
    assert "nanopnl |" not in content


def _require_bash() -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash not available on this environment")
    probe = subprocess.run(
        ["bash", "-lc", "echo ok"],
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("bash present but not runnable in this environment")


def _sandbox_root(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)

    # Copy scripts under test.
    for script_name in ("nanobot_aliases.sh", "nanokill.sh", "nanorestart.sh"):
        src = REPO_ROOT / "scripts" / script_name
        dst = scripts / script_name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR)

    # Stub nanoup.sh used by nanorestart.sh.
    nanoup = scripts / "nanoup.sh"
    nanoup.write_text("#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n", encoding="utf-8")
    nanoup.chmod(nanoup.stat().st_mode | stat.S_IXUSR)

    # Minimal pnl_report.py for nanostatus/nanorestart path.
    pnl_report = scripts / "pnl_report.py"
    pnl_report.write_text("print('USDC: $1.00')\n", encoding="utf-8")
    return root


def test_nanokill_and_nanorestart_scripts_execute_in_sandbox(tmp_path: Path):
    _require_bash()
    root = _sandbox_root(tmp_path)
    env = {**os.environ, "NANOCLAW_ROOT": str(root)}

    run_kill = subprocess.run(
        ["bash", str(root / "scripts" / "nanokill.sh")],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run_kill.returncode == 0, run_kill.stderr

    run_restart = subprocess.run(
        ["bash", str(root / "scripts" / "nanorestart.sh")],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run_restart.returncode == 0, run_restart.stderr


def test_alias_functions_nanostatus_and_nanokill_are_callable(tmp_path: Path):
    _require_bash()
    root = _sandbox_root(tmp_path)
    env = {**os.environ, "NANOCLAW_ROOT": str(root)}

    cmd = "source scripts/nanobot_aliases.sh && nanostatus && nanokill"
    result = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
