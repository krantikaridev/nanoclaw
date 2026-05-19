from modules.runtime import TradeDecision, Balances
from modules.swap_executor import (
    _decision_notional_usd,
    _profit_take_balance_relief_bypass_allowed,
    _profit_take_balance_relief_signal_strength,
    _resolve_x_signal_enhanced_fallback_execution,
    _x_signal_equity_effective_dust_min,
    _x_signal_gated_trade_relaxed_slippage,
    _x_signal_min_trade_guard_bypass,
    _x_signal_small_high_conviction_relaxed_slippage,
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


def test_profit_take_balance_relief_bypass_requires_balance_notional_and_signal():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.75,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "TP_HIT"},
    )


def test_profit_take_balance_relief_bypass_rejects_sub_floor_notional():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5.0 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )


def test_profit_take_balance_relief_bypass_rejects_weak_signal():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.59,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )


def test_profit_take_balance_relief_bypass_rejects_low_wmatic_stack():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=7.0, pol=1.0)
    assert not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )


def test_profit_take_balance_relief_bypass_accepts_notional_at_relaxed_floor():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(6.6 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )


def test_profit_take_balance_relief_signal_strength_defaults_when_absent():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
    )
    assert _profit_take_balance_relief_signal_strength(decision, None) == 0.60


def test_profit_take_balance_relief_signal_strength_from_profit_signal_gain_pct():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "TP_HIT", "gain_pct": 8.0, "peak_gain_pct": 8.0, "pullback_pct": 0.0},
    )
    assert strength == pytest.approx(0.80)


def test_profit_take_balance_relief_signal_strength_prefers_profit_signal_explicit():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.55,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"signal_strength": 0.72, "reason": "HOLD"},
    )
    assert strength == pytest.approx(0.72)


def test_profit_take_balance_relief_signal_strength_hold_is_weak():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.90,
    )
    assert _profit_take_balance_relief_signal_strength(
        decision, {"reason": "HOLD"}
    ) == pytest.approx(0.0)


def test_profit_take_balance_relief_signal_strength_strong_exit_outranks_tp_hit():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
    )
    tp = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "TP_HIT", "gain_pct": 8.0, "peak_gain_pct": 8.0},
    )
    strong = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "STRONG_TP_HIT", "gain_pct": 8.0, "peak_gain_pct": 8.0},
    )
    assert strong > tp
    assert strong >= 0.88


def test_profit_take_balance_relief_bypass_rejects_hold_despite_decision_strength():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.90,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "HOLD"},
    )


def test_profit_take_balance_relief_bypass_qualifies_via_profit_signal_metrics():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(7 * 1_000_000_000_000_000_000),
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=15.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "TP_HIT", "gain_pct": 7.0, "peak_gain_pct": 7.0},
    )


def test_profit_take_balance_relief_bypass_allows_wmatic_to_usdc():
    decision = TradeDecision(
        direction="WMATIC_TO_USDC",
        amount_in=int(8 * 1_000_000_000_000_000_000),
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )


def test_profit_take_balance_relief_bypass_allows_notional_above_old_max_band():
    """TEMPORARY: no $10 upper cap — any sub-MIN notional >= floor may qualify."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(9.5 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=15.0,
    )


def test_x_signal_small_high_conviction_relaxed_slippage_for_usdc_to_equity(monkeypatch):
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_PRIMARY_BPS",
        8000,
    )
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_RETRY_BPS",
        10000,
    )
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=11_000_000,
        trade_size=11.0,
        signal_strength=0.90,
    )
    slip = _x_signal_small_high_conviction_relaxed_slippage(decision, decision_notional_usd=11.0)
    assert slip == (8000, 10000)


def test_x_signal_small_high_conviction_relaxed_slippage_rejects_large_notional():
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=20_000_000,
        trade_size=20.0,
        signal_strength=0.90,
    )
    assert _x_signal_small_high_conviction_relaxed_slippage(decision, decision_notional_usd=20.0) is None


def test_x_signal_gated_trade_relaxed_slippage_for_usdc_to_equity_at_min_gate(monkeypatch):
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_GATED_TRADE_FALLBACK_PRIMARY_BPS",
        9000,
    )
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_GATED_TRADE_FALLBACK_RETRY_BPS",
        12000,
    )
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=20_000_000,
        trade_size=20.0,
        signal_strength=0.90,
    )
    slip = _x_signal_gated_trade_relaxed_slippage(decision, decision_notional_usd=20.0)
    assert slip == (9000, 12000)


def test_x_signal_gated_trade_relaxed_slippage_rejects_below_min_gate():
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=17_000_000,
        trade_size=17.0,
        signal_strength=0.90,
    )
    assert _x_signal_gated_trade_relaxed_slippage(decision, decision_notional_usd=17.0) is None


def test_resolve_x_signal_enhanced_fallback_prefers_small_over_gated(monkeypatch):
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_PRIMARY_BPS",
        8000,
    )
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_RETRY_BPS",
        10000,
    )
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=11_000_000,
        trade_size=11.0,
        signal_strength=0.90,
    )
    resolved = _resolve_x_signal_enhanced_fallback_execution(decision, decision_notional_usd=11.0)
    assert resolved == (8000, 10000, None)


def test_resolve_x_signal_enhanced_fallback_gated_includes_min_out_extra(monkeypatch):
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_GATED_TRADE_FALLBACK_PRIMARY_BPS",
        9000,
    )
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_GATED_TRADE_FALLBACK_RETRY_BPS",
        12000,
    )
    monkeypatch.setattr(
        "modules.swap_executor.cfg.X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS",
        75,
    )
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=22_000_000,
        trade_size=22.0,
        signal_strength=0.75,
    )
    resolved = _resolve_x_signal_enhanced_fallback_execution(decision, decision_notional_usd=22.0)
    assert resolved == (9000, 12000, 75)


def test_x_signal_equity_effective_dust_min_requires_healthy_stables(monkeypatch):
    monkeypatch.setattr("modules.swap_executor._facade", lambda: __import__("clean_swap"))
    monkeypatch.setattr("clean_swap.MIN_TRADE_USD", 15.0)
    monkeypatch.setattr("clean_swap.X_SIGNAL_EQUITY_DUST_MIN_USD", 7.5)
    b_low = Balances(usdt=10.0, usdc=60.0, wmatic=0.0, pol=0.0)
    assert _x_signal_equity_effective_dust_min(b_low) is None
    b_ok = Balances(usdt=50.0, usdc=50.0, wmatic=0.0, pol=0.0)
    assert _x_signal_equity_effective_dust_min(b_ok) == pytest.approx(7.5)
