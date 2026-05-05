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
    assert "standalone nano* command shims" in content
    # Guard against accidental legacy alias block duplication.
    assert content.startswith("#!/usr/bin/env bash\n")
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

    # Runtime artifacts read by nanodaily script.
    (root / ".env").write_text("TEST_MODE=true\n", encoding="utf-8")
    (root / "real_cron.log").write_text(
        "HARD BYPASS\nskip cycle\nTRADE SKIPPED\n",
        encoding="utf-8",
    )

    # Copy nanodaily executable under test.
    nanodaily_src = REPO_ROOT / "nanodaily"
    nanodaily_dst = root / "nanodaily"
    nanodaily_dst.write_text(nanodaily_src.read_text(encoding="utf-8"), encoding="utf-8")
    nanodaily_dst.chmod(nanodaily_dst.stat().st_mode | stat.S_IXUSR)

    # Stub git used by nanodaily ("git rev-parse --short HEAD").
    bin_dir = root / "bin"
    bin_dir.mkdir()
    git_stub = bin_dir / "git"
    git_stub.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"rev-parse\" ]]; then\n"
        "  echo deadbee\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    git_stub.chmod(git_stub.stat().st_mode | stat.S_IXUSR)
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


def test_nanostatus_forwards_cli_args_to_pnl_report(tmp_path: Path):
    _require_bash()
    root = _sandbox_root(tmp_path)
    env = {**os.environ, "NANOCLAW_ROOT": str(root)}
    (root / "scripts" / "pnl_report.py").write_text(
        "import sys\nprint('ARGS:' + ' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    cmd = "source scripts/nanobot_aliases.sh && nanostatus --reset-session"
    result = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ARGS:--reset-session" in result.stdout


def test_sourcing_aliases_preserves_caller_shell_options(tmp_path: Path):
    _require_bash()
    root = _sandbox_root(tmp_path)
    env = {**os.environ, "NANOCLAW_ROOT": str(root)}

    cmd = (
        "set +e +u; set +o pipefail; "
        "source scripts/nanobot_aliases.sh; "
        "set -o | awk '/errexit|nounset|pipefail/ {print $1 \"=\" $2}'"
    )
    result = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "errexit=off" in result.stdout
    assert "nounset=off" in result.stdout
    assert "pipefail=off" in result.stdout


def test_install_mode_creates_standalone_command_shims(tmp_path: Path):
    _require_bash()
    root = _sandbox_root(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    (fake_home / ".bashrc").write_text("", encoding="utf-8")
    env = {**os.environ, "HOME": str(fake_home), "NANOCLAW_ROOT": str(root)}

    install = subprocess.run(
        ["bash", str(root / "scripts" / "nanobot_aliases.sh"), "--install"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    bindir = fake_home / ".local" / "bin"
    assert (bindir / "nanostatus").is_file()
    assert (bindir / "nanopnl").is_file()
    assert (bindir / "nanodaily").is_file()

    run_status = subprocess.run(
        ["bash", "-lc", 'export PATH="$HOME/.local/bin:$PATH"; nanostatus'],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run_status.returncode == 0, run_status.stderr
    assert "USDC: $1.00" in run_status.stdout


def test_nanodaily_runs_from_outside_repo_root(tmp_path: Path):
    _require_bash()
    root = _sandbox_root(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    }

    run_daily = subprocess.run(
        ["bash", str(root / "nanodaily")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run_daily.returncode == 0, run_daily.stderr
    assert "can't open file" not in run_daily.stdout
    assert "USDC: $1.00" in run_daily.stdout
