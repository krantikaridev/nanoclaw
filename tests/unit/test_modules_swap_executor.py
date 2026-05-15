from modules.runtime import TradeDecision, Balances
from modules.swap_executor import (
    _decision_notional_usd,
    _x_signal_equity_effective_dust_min,
    _x_signal_min_trade_guard_bypass,
)
import pytest


def test_decision_notional_usd_prefers_explicit_trade_size():
    d = TradeDecision(direction="USDT_TO_WMATIC", amount_in=1, trade_size=27.5)
    assert _decision_notional_usd(d, current_price_usd=0.0) == 27.5


def test_decision_notional_usd_converts_stable_input_amount_in_6_decimals():
    d = TradeDecision(direction="USDC_TO_EQUITY", amount_in=4_500_000)
    assert _decision_notional_usd(d, current_price_usd=0.0) == 4.5


def test_decision_notional_usd_converts_wmatic_input_amount_in_18_decimals():
    d = TradeDecision(direction="WMATIC_TO_USDT", amount_in=int(8 * 1_000_000_000_000_000_000))
    assert _decision_notional_usd(d, current_price_usd=2.0) == 16.0


def test_decision_notional_usd_returns_none_for_wmatic_input_when_price_missing():
    d = TradeDecision(direction="WMATIC_TO_USDT", amount_in=int(8 * 1_000_000_000_000_000_000))
    assert _decision_notional_usd(d, current_price_usd=0.0) is None


def test_x_signal_min_trade_guard_bypass_high_conviction_usdc_to_equity():
    d = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=7_990_000,
        trade_size=7.99,
        signal_strength=0.90,
    )
    assert _x_signal_min_trade_guard_bypass(d, decision_notional_usd=7.99, min_trade_usd=10.0)


def test_x_signal_min_trade_guard_bypass_rejects_below_override_floor():
    d = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=7_400_000,
        trade_size=7.4,
        signal_strength=0.92,
    )
    assert not _x_signal_min_trade_guard_bypass(d, decision_notional_usd=7.4, min_trade_usd=10.0)


def test_x_signal_min_trade_guard_bypass_rejects_low_strength():
    d = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=7_990_000,
        trade_size=7.99,
        signal_strength=0.80,
    )
    assert not _x_signal_min_trade_guard_bypass(d, decision_notional_usd=7.99, min_trade_usd=10.0)


def test_x_signal_min_trade_guard_bypass_rejects_non_equity_direction():
    d = TradeDecision(
        direction="USDC_TO_WMATIC",
        amount_in=7_990_000,
        trade_size=7.99,
        signal_strength=0.92,
    )
    assert not _x_signal_min_trade_guard_bypass(d, decision_notional_usd=7.99, min_trade_usd=10.0)


def test_x_signal_equity_effective_dust_min_requires_healthy_stables(monkeypatch):
    monkeypatch.setattr("modules.swap_executor._facade", lambda: __import__("clean_swap"))
    monkeypatch.setattr("clean_swap.MIN_TRADE_USD", 15.0)
    monkeypatch.setattr("clean_swap.X_SIGNAL_EQUITY_DUST_MIN_USD", 7.5)
    b_low = Balances(usdt=10.0, usdc=60.0, wmatic=0.0, pol=0.0)
    assert _x_signal_equity_effective_dust_min(b_low) is None
    b_ok = Balances(usdt=50.0, usdc=50.0, wmatic=0.0, pol=0.0)
    assert _x_signal_equity_effective_dust_min(b_ok) == pytest.approx(7.5)
