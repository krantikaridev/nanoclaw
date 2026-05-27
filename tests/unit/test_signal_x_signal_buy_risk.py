"""Unit tests for X-SIGNAL USDC→equity BUY risk (combined stables buffer)."""

from __future__ import annotations

import pytest

from modules import signal as signal_module


@pytest.fixture
def vm_threshold(monkeypatch):
    monkeypatch.setattr(signal_module.cfg, "PROTECTION_FLUCTUATION_USDT_THRESHOLD", 12.0, raising=False)
    monkeypatch.setattr(signal_module.cfg, "PROTECTION_FLUCTUATION_MIN_WMATIC", 0.0, raising=False)


def _assess(*, usdt: float, usdc: float, wmatic: float):
    return signal_module._assess_x_signal_buy_risk(
        onchain_usdt=usdt,
        onchain_usdc=usdc,
        onchain_wmatic=wmatic,
    )


def test_buy_risk_low_when_usdt_low_but_combined_stables_ample(vm_threshold):
    """VM steady state: USDT below high buffer but STABLE_USD clears rotation."""
    level, ctx = _assess(usdt=9.27, usdc=30.90, wmatic=156.0)

    assert level == "LOW"
    assert "usdt_below_high_buffer" not in (ctx.get("reasons") or [])
    assert float(ctx["onchain_stable_usd"]) == pytest.approx(40.17, abs=0.01)


def test_buy_risk_high_when_combined_stables_genuinely_low(vm_threshold):
    level, ctx = _assess(usdt=9.0, usdc=2.0, wmatic=156.0)

    assert level == "HIGH"
    assert "usdt_below_high_buffer" in (ctx.get("reasons") or [])


def test_buy_risk_low_happy_path_usdt_alone_sufficient(vm_threshold, monkeypatch):
    """USDT above high buffer with no false HIGH when USDC=0 (WMATIC below medium guard)."""
    monkeypatch.setattr(signal_module.cfg, "PROTECTION_FLUCTUATION_MIN_WMATIC", 100.0, raising=False)
    level, ctx = _assess(usdt=20.0, usdc=0.0, wmatic=50.0)

    assert level == "LOW"
    assert "usdt_below_high_buffer" not in (ctx.get("reasons") or [])


def test_buy_risk_medium_uses_combined_stables_for_buffer(vm_threshold, monkeypatch):
    monkeypatch.setattr(signal_module.cfg, "PROTECTION_FLUCTUATION_MIN_WMATIC", 5.0, raising=False)

    level, ctx = _assess(usdt=10.0, usdc=20.0, wmatic=10.0)
    assert level == "LOW"
    assert "usdt_below_medium_buffer_and_wmatic_high" not in (ctx.get("reasons") or [])

    # stable 16: above high_trigger 15, below medium_trigger 21
    level2, ctx2 = _assess(usdt=16.0, usdc=0.0, wmatic=10.0)
    assert level2 == "MEDIUM"
    assert "usdt_below_medium_buffer_and_wmatic_high" in (ctx2.get("reasons") or [])


def test_cycle_risk_level_low_when_usdt_low_but_combined_stables_ample(vm_threshold):
    """_x_signal_buy_risk_level matches assess path for defensive_pause / cycle gate."""
    level = signal_module._x_signal_buy_risk_level(usdt=9.27, usdc=30.90, wmatic=156.0)
    assert level == "LOW"


def test_cycle_risk_level_high_when_combined_stables_genuinely_low(vm_threshold):
    level = signal_module._x_signal_buy_risk_level(usdt=9.0, usdc=2.0, wmatic=156.0)
    assert level == "HIGH"


def test_buy_risk_divergence_still_usdt_only(vm_threshold, monkeypatch):
    monkeypatch.setattr(
        signal_module.cfg,
        "env_float",
        lambda key, default: 5.0 if key == "X_SIGNAL_BUY_RISK_HIGH_USDT_DIVERGENCE_USD" else default,
    )
    level, ctx = signal_module._assess_x_signal_buy_risk(
        onchain_usdt=20.0,
        onchain_usdc=30.0,
        onchain_wmatic=156.0,
        snapshot_usdt=50.0,
    )

    assert level == "HIGH"
    assert "very_large_usdt_divergence" in (ctx.get("reasons") or [])
    assert "usdt_below_high_buffer" not in (ctx.get("reasons") or [])


def test_reduced_high_risk_xsignal_eligible(monkeypatch):
    monkeypatch.setattr(signal_module, "allow_reduced_high_risk_xsignal", lambda: True)
    assert signal_module.reduced_high_risk_xsignal_eligible(
        total_portfolio_usd=140.0,
        signal_strength=0.85,
    )
    assert not signal_module.reduced_high_risk_xsignal_eligible(
        total_portfolio_usd=120.0,
        signal_strength=0.85,
    )
    assert not signal_module.reduced_high_risk_xsignal_eligible(
        total_portfolio_usd=140.0,
        signal_strength=0.75,
    )


def test_apply_reduced_high_risk_xsignal_override(monkeypatch):
    monkeypatch.setattr(signal_module, "allow_reduced_high_risk_xsignal", lambda: True)
    mult, skip, applied = signal_module._apply_reduced_high_risk_xsignal_override(
        risk_level="HIGH",
        skip_buys=True,
        buy_mult=0.0,
        total_portfolio_usd=140.0,
        max_buy_signal_strength=0.82,
    )
    assert applied
    assert mult == pytest.approx(0.40)
    assert skip is False

    mult2, skip2, applied2 = signal_module._apply_reduced_high_risk_xsignal_override(
        risk_level="HIGH",
        skip_buys=True,
        buy_mult=0.0,
        total_portfolio_usd=140.0,
        max_buy_signal_strength=0.70,
    )
    assert not applied2
    assert mult2 == 0.0
    assert skip2 is True


def test_apply_reduced_high_risk_disabled_by_env(monkeypatch):
    monkeypatch.setattr(signal_module, "allow_reduced_high_risk_xsignal", lambda: False)
    mult, skip, applied = signal_module._apply_reduced_high_risk_xsignal_override(
        risk_level="HIGH",
        skip_buys=True,
        buy_mult=0.0,
        total_portfolio_usd=200.0,
        max_buy_signal_strength=0.95,
    )
    assert not applied
    assert mult == 0.0
    assert skip is True
