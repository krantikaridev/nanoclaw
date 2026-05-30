"""Tests for scripts/unpause_readiness.py (Grok F gates in code)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.unpause_readiness import CheckResult, format_report, run_checks


def _write_env(root: Path, **kwargs: str) -> None:
    lines = [f"{k}={v}" for k, v in kwargs.items()]
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_followed(root: Path, symbols: list[str]) -> None:
    assets = [{"symbol": s, "address": "0x" + "a" * 40, "decimals": 18} for s in symbols]
    (root / "followed_equities.json").write_text(
        json.dumps({"enabled": True, "assets": assets}),
        encoding="utf-8",
    )


def test_run_checks_passes_with_safe_defaults(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_env(
        root,
        ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL="false",
        FE_STABLE_RUNWAY_ENABLED="true",
        COPY_TRADING_ENABLED="false",
        X_SIGNAL_HONOR_FULL_BLOCKLIST="false",
    )
    _write_followed(root, ["WETH_ALPHA"])
    (root / ".xsignal_blocked_symbols").write_text("LINK_ALPHA\n", encoding="utf-8")
    (root / "control.json").write_text(
        json.dumps({"paused": True, "operator_pause_lock": True}),
        encoding="utf-8",
    )

    import modules.runtime as runtime

    monkeypatch.setattr(runtime, "get_pol_balance", lambda: 0.25)
    monkeypatch.setattr(runtime, "_pol_target_for_trade", lambda *_a, **_k: 0.20)
    monkeypatch.setattr(
        runtime,
        "get_balances",
        lambda: runtime.Balances(usdt=0.0, usdc=18.0, wmatic=0.0, pol=15.0, followed_equity_usd=112.0),
    )
    monkeypatch.setattr(runtime, "compute_authoritative_total_usd", lambda _b: 131.0)

    results = run_checks(root)
    hard = [r for r in results if r.severity == "hard"]
    assert all(r.passed for r in hard), format_report(results)


def test_run_checks_fails_when_all_blocked_without_honor(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_env(
        root,
        ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL="false",
        FE_STABLE_RUNWAY_ENABLED="true",
        COPY_TRADING_ENABLED="false",
        X_SIGNAL_HONOR_FULL_BLOCKLIST="false",
    )
    _write_followed(root, ["WETH_ALPHA", "LINK_ALPHA"])
    (root / ".xsignal_blocked_symbols").write_text(
        "WETH_ALPHA\nLINK_ALPHA\n",
        encoding="utf-8",
    )

    results = run_checks(root)
    honor = next(r for r in results if r.name == "honor_full_blocklist")
    assert honor.passed is False
    assert honor.severity == "hard"


def test_run_checks_fails_when_loss_cut_enabled(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_env(
        root,
        ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL="true",
        FE_STABLE_RUNWAY_ENABLED="true",
        COPY_TRADING_ENABLED="false",
    )
    _write_followed(root, ["WETH_ALPHA"])

    results = run_checks(root)
    loss = next(r for r in results if r.name == "loss_cut_off")
    assert loss.passed is False


def test_format_report_marks_hard_fail() -> None:
    text = format_report(
        [
            CheckResult("loss_cut_off", False, "ALLOW=true", "hard"),
            CheckResult("control_pause", True, "paused=true", "info"),
        ]
    )
    assert "FAIL loss_cut_off" in text
    assert "OVERALL: FAIL" in text
