from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_nanobot_aliases_script_defines_core_functions():
    script_path = REPO_ROOT / "scripts" / "nanobot_aliases.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "nanoup()" in content
    assert "nanokill()" in content
    assert "nanostatus()" in content
    assert "nanopnl()" in content
    assert "nanorestart()" in content
    assert "nanobot()" in content
    assert "nanoattach()" in content


def test_nanobot_aliases_script_supports_install_mode():
    script_path = REPO_ROOT / "scripts" / "nanobot_aliases.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "--install" in content
    assert "source ~/.bashrc" in content


def test_nanokill_and_nanorestart_scripts_exist():
    assert (REPO_ROOT / "scripts" / "nanokill.sh").is_file()
    assert (REPO_ROOT / "scripts" / "nanorestart.sh").is_file()
