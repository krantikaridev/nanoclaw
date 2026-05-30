#!/usr/bin/env python3
"""Normalize shell scripts to LF (fixes VM 'syntax error near unexpected token (' on nh())."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalize_tree(root: Path) -> list[str]:
    fixed: list[str] = []
    for pattern in ("scripts/*.sh", "nanodaily", "external_layer/*.sh"):
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            raw = path.read_bytes()
            if b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf"):
                continue
            text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            if text.startswith("\ufeff"):
                text = text[1:]
            path.write_text(text, encoding="utf-8", newline="\n")
            try:
                path.chmod(path.stat().st_mode | 0o111)
            except OSError:
                pass
            fixed.append(str(path.relative_to(root)))
    return fixed


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    fixed = normalize_tree(root)
    if fixed:
        print(f"[nanoclaw] normalize_shell_lf: fixed {len(fixed)} file(s)")
        for name in fixed:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
