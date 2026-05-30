"""Tests for scripts/normalize_shell_lf.py."""

from __future__ import annotations

from pathlib import Path

from scripts.normalize_shell_lf import normalize_tree


def test_normalize_tree_strips_crlf(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    target = scripts / "nanobot_aliases.sh"
    target.write_bytes(b"nh() {\r\n  echo ok\r\n}\r\n")
    fixed = normalize_tree(tmp_path)
    assert "scripts/nanobot_aliases.sh" in fixed
    assert b"\r" not in target.read_bytes()
    assert target.read_text(encoding="utf-8") == "nh() {\n  echo ok\n}\n"
