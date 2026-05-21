from modules.runtime import TradeDecision, Balances
from modules.swap_executor import (
    _decision_notional_usd,
    _profit_take_balance_relief_bypass_allowed,
    _profit_take_balance_relief_signal_strength,
    _profit_take_bump_cycle_counter,
    _profit_take_force_small_relief_eligible,
    _profit_take_record_exit,
    _MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN,
    _MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN,
    _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH,
    _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_NOTIONAL_FLOOR_USD,
    _resolve_x_signal_enhanced_fallback_execution,
    _x_signal_equity_effective_dust_min,
    _x_signal_gated_trade_enhanced_execution_eligible,
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


def test_profit_take_balance_relief_bypass_rejects_sub_floor_notional(capsys):
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(2.99 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )
    captured = capsys.readouterr().out
    assert "[nanoclaw] P2 relief check" in captured
    assert "notional=$2.99" in captured
    assert "allowed=False" in captured
    assert "reason=notional_below_floor" in captured
    assert "floor=$3.00" in captured


def test_profit_take_force_small_relief_eligible_requires_cycles_and_floor():
    assert not _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=20.0,
        notional_usd=3.5,
        cycles_since_exit=_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN - 1,
    )
    assert _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=20.0,
        notional_usd=3.5,
        cycles_since_exit=_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN,
    )
    assert not _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=_MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN - 0.01,
        notional_usd=3.5,
        cycles_since_exit=10,
    )
    assert not _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=20.0,
        notional_usd=_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_NOTIONAL_FLOOR_USD - 0.01,
        cycles_since_exit=10,
    )


def test_profit_take_balance_relief_bypass_force_weak_signal_after_idle_cycles(capsys):
    """TEMPORARY SPRINT FIX - May 2026: force-allow weak signal when WMATIC ≥ $8 and idle 5+ cycles."""
    state: dict = {}
    for _ in range(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN):
        _profit_take_bump_cycle_counter(state)
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(3.4 * 1_000_000_000_000_000_000),
        signal_strength=0.20,
    )
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=Balances(usdt=10.0, wmatic=20.0, pol=1.0, usdc=30.0),
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "HOLD"},
        state=state,
    )
    captured = capsys.readouterr().out
    assert "FORCE small profit take | WMATIC healthy, forcing exit" in captured
    assert "force_no_exit_cycles" in captured


def test_profit_take_record_exit_resets_cycle_counter():
    state: dict = {}
    _profit_take_bump_cycle_counter(state)
    _profit_take_bump_cycle_counter(state)
    assert state["profit_take_rotation"]["cycles_since_exit"] == 2
    _profit_take_record_exit(state)
    assert state["profit_take_rotation"]["cycles_since_exit"] == 0


def test_profit_take_balance_relief_bypass_rejects_weak_signal():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.40,
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
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=6.5, pol=1.0)
    assert not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )


def test_profit_take_balance_relief_bypass_accepts_notional_at_relaxed_floor(capsys):
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(3.0 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )
    captured = capsys.readouterr().out
    assert "[nanoclaw] P2 relief check" in captured
    assert "notional=$3.00" in captured
    assert "allowed=True" in captured


def test_profit_take_balance_relief_bypass_accepts_observed_production_notional(capsys):
    """TEMPORARY sprint (20 May): ~$3.38–$3.39 profit-take sizes pass at $3.0 floor."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(3.38 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )
    captured = capsys.readouterr().out
    assert "notional=$3.38" in captured
    assert "allowed=True" in captured


def test_profit_take_balance_relief_bypass_accepts_notional_between_old_and_new_floor(capsys):
    """TEMPORARY sprint: notionals in the $3.50–$5 band qualify (were blocked at prior $5 floor)."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(3.6 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )
    captured = capsys.readouterr().out
    assert "notional=$3.60" in captured
    assert "allowed=True" in captured


def test_profit_take_balance_relief_signal_strength_defaults_when_absent():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
    )
    assert _profit_take_balance_relief_signal_strength(decision, None) == 0.55


def test_profit_take_balance_relief_signal_strength_boosts_healthy_wmatic_stack():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        None,
        wmatic_usd_equiv=20.0,
    )
    assert strength >= _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH


def test_profit_take_balance_relief_signal_strength_healthy_wmatic_never_below_half():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),
        signal_strength=0.05,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "MOMENTUM_FADE", "gain_pct": 0.0, "peak_gain_pct": 0.0},
        wmatic_usd_equiv=8.0,
    )
    assert strength >= _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH


def test_profit_take_balance_relief_signal_strength_healthy_exit_reason_at_least_fifty_five():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),
        signal_strength=0.10,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "TP_HIT", "gain_pct": 0.2, "peak_gain_pct": 0.2, "pullback_pct": 0.0},
        wmatic_usd_equiv=10.0,
    )
    assert strength >= _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH


def test_profit_take_balance_relief_signal_strength_ignores_hold_when_wmatic_healthy():
    """TEMPORARY SPRINT FIX - May 2026: HOLD must not block relief when stack ≥ $7."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(3.99 * 1_000_000_000_000_000_000),
        signal_strength=0.75,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "HOLD", "gain_pct": 2.0, "peak_gain_pct": 3.0},
        wmatic_usd_equiv=12.0,
    )
    assert strength >= _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH


def test_profit_take_balance_relief_bypass_allows_small_exit_with_hold_and_healthy_stack(capsys):
    """TEMPORARY SPRINT FIX - May 2026: ~$3.99 main rotation sell with HOLD snapshot."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(3.99 * 1_000_000_000_000_000_000),
        signal_strength=0.75,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=200.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "HOLD", "gain_pct": 2.0, "peak_gain_pct": 3.0},
    )
    captured = capsys.readouterr().out
    assert "notional=$3.99" in captured
    assert "allowed=True" in captured


def test_profit_take_balance_relief_signal_strength_from_profit_signal_gain_pct():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "TP_HIT", "gain_pct": 8.0, "peak_gain_pct": 8.0, "pullback_pct": 0.0},
    )
    assert strength >= 0.85


def test_profit_take_balance_relief_signal_strength_trailing_stop_ranks_high():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {
            "reason": "TRAILING_STOP_HIT",
            "gain_pct": 5.0,
            "peak_gain_pct": 9.0,
            "pullback_pct": 3.0,
        },
    )
    assert strength >= 0.90


def test_profit_take_balance_relief_signal_strength_prefers_profit_signal_explicit():
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.55,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"signal_strength": 0.72, "reason": "TP_HIT"},
        wmatic_usd_equiv=6.0,
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


def test_profit_take_balance_relief_signal_strength_modest_tp_hit_meets_floor():
    """May 2026 sprint: modest TP_HIT gains still clear the P2 relief floor."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "TP_HIT", "gain_pct": 1.2, "peak_gain_pct": 1.5, "pullback_pct": 0.0},
    )
    assert strength >= 0.58
    assert strength > 0.0


def test_profit_take_balance_relief_signal_strength_weak_exit_boosted_by_healthy_wmatic():
    """May 2026 sprint: healthy WMATIC stack nudges borderline weak exits over the floor."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),
        signal_strength=0.50,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "OTHER_EXIT", "gain_pct": 0.5, "peak_gain_pct": 0.5},
        wmatic_usd_equiv=12.0,
    )
    assert strength >= _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH
    assert strength > 0.0


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
    assert strong >= 0.93


def test_profit_take_balance_relief_bypass_small_trade_decent_balance_trailing_stop():
    """TEMPORARY sprint: sub-MIN notional qualifies when WMATIC stack is healthy + strong exit."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=12.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={
            "reason": "TRAILING_STOP_HIT",
            "gain_pct": 4.0,
            "peak_gain_pct": 7.0,
            "pullback_pct": 2.0,
        },
    )


def test_profit_take_balance_relief_bypass_rejects_hold_when_wmatic_stack_small():
    """HOLD still blocks relief when total WMATIC USD equiv is below the $7 floor."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.90,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=6.0, pol=1.0)
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


def test_x_signal_gated_trade_relaxed_slippage_uses_plan_flag_without_notional_gate():
    """TEMPORARY sprint: explicit x_signal_gated_execution scopes enhanced execution."""
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=12_000_000,
        trade_size=12.0,
        signal_strength=0.90,
        x_signal_gated_execution=True,
    )
    assert _x_signal_gated_trade_enhanced_execution_eligible(decision, decision_notional_usd=12.0)
    slip = _x_signal_gated_trade_relaxed_slippage(decision, decision_notional_usd=12.0)
    assert slip is not None
    resolved = _resolve_x_signal_enhanced_fallback_execution(decision, decision_notional_usd=12.0)
    assert resolved is not None
    assert resolved[2] == 75


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
