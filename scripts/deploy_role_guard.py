#!/usr/bin/env python3
"""Deploy role guards — block dangerous stage/dev branch+wallet combos."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

STAGE_WALLET = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"
DEFAULT_ROLE = "stage"


def _read_env_value(env_path: Path, key: str) -> str:
    if not env_path.is_file():
        return ""
    pattern = re.compile(rf"^{re.escape(key)}=(.*)$")
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pattern.match(line.strip())
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return ""


def _git_branch(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    return out.strip()


def check_deploy_role(
    *,
    role: str,
    branch: str,
    wallet: str,
    stage_wallet: str = STAGE_WALLET,
) -> tuple[bool, str]:
    """Return (ok, message). ok=False means nanodeploy must abort."""
    role_n = (role or DEFAULT_ROLE).strip().lower()
    branch_u = branch.strip().upper()
    wallet_l = wallet.strip().lower()
    stage_l = stage_wallet.strip().lower()

    if role_n == "dev" and branch_u == "V2":
        return False, "NANOCLAW_ROLE=dev cannot deploy branch V2 (stage track)"

    if role_n == "stage" and branch_u.startswith("V4"):
        return False, "NANOCLAW_ROLE=stage cannot deploy V4-play (lab track)"

    if branch_u.startswith("V4") and wallet_l and wallet_l == stage_l:
        return (
            False,
            f"V4-play blocked on stage wallet {stage_wallet[:6]}…{stage_wallet[-4:]} — use dev wallet",
        )

    return True, ""


def resolve_deploy_context(root: Path) -> dict[str, str]:
    env_path = root / ".env"
    role = _read_env_value(env_path, "NANOCLAW_ROLE") or DEFAULT_ROLE
    wallet = _read_env_value(env_path, "WALLET")
    branch = _git_branch(root)
    return {"role": role, "wallet": wallet, "branch": branch}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nanoclaw deploy role guard")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repo root (default: cwd)",
    )
    parser.add_argument("--role", default="", help="Override NANOCLAW_ROLE")
    parser.add_argument("--branch", default="", help="Override git branch")
    parser.add_argument("--wallet", default="", help="Override WALLET")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    ctx = resolve_deploy_context(root)
    role = args.role or ctx["role"]
    branch = args.branch or ctx["branch"]
    wallet = args.wallet or ctx["wallet"]

    ok, msg = check_deploy_role(role=role, branch=branch, wallet=wallet)
    if ok:
        print(f"deploy_role_guard: PASS role={role} branch={branch} wallet={wallet[:10]}…")
        return 0
    print(f"deploy_role_guard: BLOCKED — {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
