#!/usr/bin/env python3
"""Post-deploy unpause readiness checks (Grok Heavy F + OPERATOR_CODE_FREEZE).

Encodes the operator copy/paste playbook in code so ``nanodeploy`` / ``nanodiag``
can run the same gates every time.

Exit 0 = hard gates pass (safe to *consider* unpause; operator still sets control.json).
Exit 1 = at least one hard gate failed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    severity: str  # "hard" | "warn" | "info"


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _env_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _load_blocklist(root: Path) -> set[str]:
    for candidate in (root / ".xsignal_blocked_symbols", root / "followed_equities.json"):
        if candidate.name == ".xsignal_blocked_symbols" and candidate.is_file():
            return {
                ln.strip().upper()
                for ln in candidate.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            }
    return set()


def _followed_symbols(root: Path) -> set[str]:
    fe_path = root / "followed_equities.json"
    if not fe_path.is_file():
        return set()
    try:
        data = json.loads(fe_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    assets = data.get("assets") if isinstance(data, dict) else None
    if not isinstance(assets, list):
        return set()
    return {
        str(row.get("symbol", "")).strip().upper()
        for row in assets
        if isinstance(row, dict) and str(row.get("symbol", "")).strip()
    }


def run_checks(root: Path | None = None) -> list[CheckResult]:
    root = root or ROOT
    env = _read_env_file(root / ".env")
    results: list[CheckResult] = []

    loss_cut = _env_bool(env.get("ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL"), default=False)
    results.append(
        CheckResult(
            "loss_cut_off",
            not loss_cut,
            f"ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL={'true' if loss_cut else 'false'}",
            "hard",
        )
    )

    fe_runway = _env_bool(env.get("FE_STABLE_RUNWAY_ENABLED"), default=True)
    results.append(
        CheckResult(
            "fe_runway_enabled",
            fe_runway,
            f"FE_STABLE_RUNWAY_ENABLED={'true' if fe_runway else 'false'}",
            "hard",
        )
    )

    honor = _env_bool(env.get("X_SIGNAL_HONOR_FULL_BLOCKLIST"), default=False)
    blocked = _load_blocklist(root)
    followed = _followed_symbols(root)
    all_blocked = bool(followed) and followed.issubset(blocked)
    if all_blocked:
        results.append(
            CheckResult(
                "honor_full_blocklist",
                honor,
                f"all {len(followed)} followed assets blocked; "
                f"X_SIGNAL_HONOR_FULL_BLOCKLIST={'true' if honor else 'false'}",
                "hard",
            )
        )
    else:
        open_syms = sorted(followed - blocked) if followed else []
        results.append(
            CheckResult(
                "honor_full_blocklist",
                True,
                f"rotation open for: {', '.join(open_syms) or 'n/a'}; honor flag={honor}",
                "info",
            )
        )

    copy_enabled = _env_bool(env.get("COPY_TRADING_ENABLED"), default=False)
    if copy_enabled:
        try:
            import subprocess

            proc = subprocess.run(
                [sys.executable, str(root / "scripts" / "copy_trading_audit.py")],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
            )
            audit_rc = int(proc.returncode)
            copy_detail = f"nanocopyaudit exit={audit_rc}"
            if audit_rc != 0 and proc.stdout.strip():
                copy_detail += f" | {proc.stdout.strip().splitlines()[-1]}"
        except Exception as exc:
            audit_rc = 1
            copy_detail = f"nanocopyaudit error: {exc}"
        results.append(
            CheckResult("copy_trading_audit", audit_rc == 0, copy_detail, "hard")
        )
    else:
        results.append(
            CheckResult(
                "copy_trading_audit",
                True,
                "COPY_TRADING_ENABLED=false (copy path off — safe default)",
                "info",
            )
        )

    control_path = root / "control.json"
    if control_path.is_file():
        try:
            control = json.loads(control_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            control = {}
    else:
        control = {}
    paused = bool(control.get("paused"))
    lock = bool(control.get("operator_pause_lock"))
    results.append(
        CheckResult(
            "control_pause",
            True,
            f"paused={paused} operator_pause_lock={lock} reason={control.get('reason', '')!r}",
            "info",
        )
    )

    try:
        import modules.runtime as runtime

        pol = float(runtime.get_pol_balance())
        target = float(runtime._pol_target_for_trade(None))
        pol_ok = pol + 1e-9 >= target
        results.append(
            CheckResult(
                "pol_execution_buffer",
                pol_ok,
                f"POL={pol:.4f} target={target:.4f}",
                "warn" if not pol_ok else "info",
            )
        )
    except Exception as exc:
        results.append(
            CheckResult(
                "pol_execution_buffer",
                True,
                f"skipped (RPC unavailable): {exc}",
                "warn",
            )
        )

    try:
        import modules.runtime as runtime

        balances = runtime.get_balances()
        total = float(runtime.compute_authoritative_total_usd(balances))
        stable = float(balances.usdt) + float(balances.usdc)
        fe_usd = float(balances.followed_equity_usd)
        fe_share = fe_usd / total if total > 0 else 0.0
        target_stable = float(env.get("FE_STABLE_RUNWAY_TARGET_STABLE_USD") or 40.0)
        min_fe = float(env.get("FE_STABLE_RUNWAY_MIN_FE_SHARE") or 0.55)
        buy_blocked = (
            fe_runway
            and total > 130.0
            and fe_share + 1e-9 >= min_fe
            and stable + 1e-9 < target_stable
        )
        results.append(
            CheckResult(
                "fe_buy_guard_would_block",
                True,
                f"fe_share={fe_share:.1%} stables=${stable:.2f} "
                f"buy_blocked={'yes' if buy_blocked else 'no'}",
                "info",
            )
        )
    except Exception as exc:
        results.append(
            CheckResult(
                "fe_buy_guard_would_block",
                True,
                f"skipped: {exc}",
                "warn",
            )
        )

    commit = ""
    head_path = root / ".git" / "HEAD"
    if (root / ".git").is_dir():
        try:
            import subprocess

            commit = subprocess.check_output(
                ["git", "log", "-1", "--oneline"],
                cwd=root,
                text=True,
                timeout=10,
            ).strip()
        except Exception:
            commit = "unknown"
    results.append(CheckResult("git_head", True, commit or "n/a", "info"))

    return results


def format_report(results: list[CheckResult]) -> str:
    lines = [f"=== unpause_readiness | {ROOT} ===", ""]
    hard_fail = False
    for row in results:
        if row.severity == "hard":
            tag = "PASS" if row.passed else "FAIL"
            if not row.passed:
                hard_fail = True
        elif row.severity == "warn":
            tag = "WARN" if not row.passed else "OK"
        else:
            tag = "INFO"
        lines.append(f"{tag:4} {row.name}: {row.detail}")
    lines.append("")
    lines.append(f"OVERALL: {'PASS' if not hard_fail else 'FAIL'} (hard gates only)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    del argv
    root = Path(os.environ.get("NANOCLAW_ROOT", str(ROOT)))
    results = run_checks(root)
    print(format_report(results))
    hard_fail = any(r.severity == "hard" and not r.passed for r in results)
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
