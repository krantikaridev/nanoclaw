from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_step(name: str, command: list[str]) -> int:
    print(f"\n=== {name} ===")
    print(" ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT)
    if completed.returncode != 0:
        print(f"FAILED: {name}")
    else:
        print(f"PASSED: {name}")
    return completed.returncode


def main() -> int:
    steps = [
        ("Compile", [sys.executable, "-m", "compileall", "-q", "."]),
        ("Tests", [sys.executable, "-m", "pytest", "-q"]),
        ("Ruff", [sys.executable, "-m", "ruff", "check", "."]),
        (
            "Mypy",
            [
                sys.executable,
                "-m",
                "mypy",
                "nanoclaw/strategies",
                "nanoclaw/utils",
            ],
        ),
    ]

    for name, command in steps:
        rc = run_step(name, command)
        if rc != 0:
            return rc
    print("\nAll quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
