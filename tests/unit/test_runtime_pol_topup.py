"""AUTO-POL proactive top-up and guardrails."""

from __future__ import annotations

import time

import pytest

from modules import runtime as rt


@pytest.fixture(autouse=True)
def _reset_auto_pol_state():
    rt._AUTO_POL_FAILURE_STATE["next_retry_ts"] = 0.0
    rt._AUTO_POL_FAILURE_STATE["consecutive_failures"] = 0.0
    yield
    rt._AUTO_POL_FAILURE_STATE["next_retry_ts"] = 0.0
    rt._AUTO_POL_FAILURE_STATE["consecutive_failures"] = 0.0


def test_maybe_auto_topup_pol_skips_when_disabled(monkeypatch, capsys):
    monkeypatch.setattr(rt, "AUTO_TOPUP_POL", False)
    monkeypatch.setattr(rt, "MIN_POL_FOR_GAS", 0.15)
    monkeypatch.setattr(rt, "get_pol_balance", lambda: 0.02)

    assert rt.maybe_auto_topup_pol(context="test") is False
    out = capsys.readouterr().out
    assert "AUTO-POL skipped — disabled" in out


def test_maybe_auto_topup_pol_skips_when_sufficient(monkeypatch, capsys):
    monkeypatch.setattr(rt, "AUTO_TOPUP_POL", True)
    monkeypatch.setattr(rt, "MIN_POL_FOR_GAS", 0.15)
    monkeypatch.setattr(rt, "POL_EXECUTION_GAS_UNITS", 600_000)
    monkeypatch.setattr(rt, "POL_EXECUTION_GAS_MULTIPLIER", 1.15)
    monkeypatch.setattr(rt, "URGENT_GWEI", 120.0)
    monkeypatch.setattr(rt.GAS_PROTECTOR, "get_gas_price_gwei", lambda: 120.0)
    monkeypatch.setattr(rt, "get_pol_balance", lambda: 0.20)

    assert rt.maybe_auto_topup_pol(context="test") is True
    out = capsys.readouterr().out
    assert "AUTO-POL skipped — POL sufficient" in out
    assert "target=" in out


def test_pol_target_exceeds_static_floor_when_gas_congested(monkeypatch):
    """Repro: pol≈0.187 above MIN_POL=0.15 but below real approve+swap cost at ~350 gwei."""
    monkeypatch.setattr(rt, "MIN_POL_FOR_GAS", 0.15)
    monkeypatch.setattr(rt, "POL_EXECUTION_GAS_UNITS", 600_000)
    monkeypatch.setattr(rt, "POL_EXECUTION_GAS_MULTIPLIER", 1.15)
    monkeypatch.setattr(rt, "URGENT_GWEI", 350.0)
    monkeypatch.setattr(rt.GAS_PROTECTOR, "get_gas_price_gwei", lambda: 350.0)

    target = rt._pol_target_for_trade(None, urgent=True)
    assert target > 0.15
    assert target > 0.187
    assert rt._pol_operating_floor(None, urgent=True) < target


def test_maybe_auto_topup_considers_topup_when_pol_above_static_below_execution(
    monkeypatch, capsys,
):
    monkeypatch.setattr(rt, "AUTO_TOPUP_POL", True)
    monkeypatch.setattr(rt, "MIN_POL_FOR_GAS", 0.15)
    monkeypatch.setattr(rt, "POL_EXECUTION_GAS_UNITS", 600_000)
    monkeypatch.setattr(rt, "POL_EXECUTION_GAS_MULTIPLIER", 1.15)
    monkeypatch.setattr(rt, "URGENT_GWEI", 350.0)
    monkeypatch.setattr(rt.GAS_PROTECTOR, "get_gas_price_gwei", lambda: 350.0)
    monkeypatch.setattr(rt, "get_pol_balance", lambda: 0.187)
    monkeypatch.setattr(rt, "ensure_pol_for_trade", lambda min_pol=None, min_gas_units=None: True)

    assert rt.maybe_auto_topup_pol(context="pre_trade", force=True) is True
    out = capsys.readouterr().out
    assert "AUTO-POL consider" in out


def test_maybe_auto_topup_pol_respects_failure_cooldown(monkeypatch, capsys):
    monkeypatch.setattr(rt, "AUTO_TOPUP_POL", True)
    monkeypatch.setattr(rt, "MIN_POL_FOR_GAS", 0.15)
    monkeypatch.setattr(rt, "get_pol_balance", lambda: 0.01)
    rt._AUTO_POL_FAILURE_STATE["next_retry_ts"] = time.time() + 600.0

    assert rt.maybe_auto_topup_pol(context="test") is False
    out = capsys.readouterr().out
    assert "AUTO-POL skipped — failure cooldown" in out


def test_maybe_auto_topup_pol_force_bypasses_cooldown(monkeypatch):
    monkeypatch.setattr(rt, "AUTO_TOPUP_POL", True)
    monkeypatch.setattr(rt, "MIN_POL_FOR_GAS", 0.15)
    monkeypatch.setattr(rt, "get_pol_balance", lambda: 0.01)
    rt._AUTO_POL_FAILURE_STATE["next_retry_ts"] = time.time() + 600.0
    monkeypatch.setattr(
        rt,
        "ensure_pol_for_trade",
        lambda min_pol=None, min_gas_units=None: True,
    )

    assert rt.maybe_auto_topup_pol(context="pre_trade", force=True) is True


def test_ensure_pol_for_trade_skips_when_pol_too_low_for_tx(monkeypatch, capsys):
    monkeypatch.setattr(rt, "get_pol_balance", lambda: 0.001)
    monkeypatch.setattr(rt, "POL_MIN_BALANCE_FOR_TOPUP_TX", 0.006)

    assert rt.ensure_pol_for_trade(min_pol=0.15) is False
    out = capsys.readouterr().out
    assert "POL too low to broadcast top-up txs" in out
    assert "send native POL manually" in out


def test_ensure_pol_for_trade_uses_min_trade_usd_for_usdt_leg_threshold(monkeypatch):
    monkeypatch.setattr(rt, "MIN_TRADE_USD", 7.5)
    assert rt._pol_topup_min_usdt_swap() == 7.5
