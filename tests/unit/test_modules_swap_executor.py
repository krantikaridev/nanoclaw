import time

from modules.runtime import TradeDecision, Balances
from config import MIN_NET_EDGE_PCT
from modules import swap_executor as swap_exec_mod
from modules.swap_executor import (
    _MIN_NET_EDGE_PCT,
    _decision_notional_usd,
    _infer_expected_gross_edge_pct,
    _log_min_net_edge_policy_once,
    _min_net_edge_floor_pct,
    _profit_take_balance_relief_bypass_allowed,
    _reject_if_low_expected_net_edge,
    _profit_take_balance_relief_signal_strength,
    _profit_take_bump_cycle_counter,
    _profit_take_force_small_relief_eligible,
    _profit_take_record_exit,
    _profit_take_wmatic_stack_low,
    _main_strategy_stable_rotation_fallback,
    _MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN,
    _MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD,
    _MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN,
    _MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN,
    _MAIN_STRATEGY_LOW_WMATIC_FORCE_WM_MIN_USD,
    _MAIN_STRATEGY_LOW_WMATIC_P2_SIGNAL_MIN,
    _MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_CYCLES_MIN,
    _MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_CYCLES_MIN,
    _MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_SIGNAL,
    _MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_MIN_SIGNAL,
    _main_strategy_idle_rotation_sell_decision,
    _main_strategy_idle_rotation_eligibility,
    _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH,
    _MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_NOTIONAL_FLOOR_USD,
    _resolve_x_signal_enhanced_fallback_execution,
    _record_x_signal_stf_failure,
    _x_signal_apply_stf_pause_filter,
    _x_signal_stf_pause_active,
    _x_signal_equity_effective_dust_min,
    _x_signal_gated_trade_enhanced_execution_eligible,
    _x_signal_gated_trade_relaxed_slippage,
    _x_signal_min_trade_guard_bypass,
    _x_signal_small_high_conviction_relaxed_slippage,
    estimate_expected_net_edge_pct,
    trade_passes_min_net_edge,
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
        amount_in=int(1.99 * 1_000_000_000_000_000_000),
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
    assert "notional=$1.99" in captured
    assert "allowed=False" in captured
    assert "reason=notional_below_floor" in captured
    assert "floor=$2.00" in captured


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
        wm_equiv_usd=_MAIN_STRATEGY_LOW_WMATIC_FORCE_WM_MIN_USD - 0.01,
        notional_usd=3.5,
        cycles_since_exit=10,
    )
    assert not _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=20.0,
        notional_usd=_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD - 0.01,
        cycles_since_exit=10,
    )


def test_profit_take_force_small_relief_eligible_at_observed_wmatic_range():
    """Signal-Driven Rotation: low stack (~$5.7) force at 3 cycles; sub-$2 stack rejected."""
    assert _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=5.7,
        notional_usd=1.9,
        cycles_since_exit=_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN,
    )
    assert not _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=1.5,
        notional_usd=1.9,
        cycles_since_exit=_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN,
    )


def test_profit_take_balance_relief_bypass_force_weak_signal_after_idle_cycles(capsys):
    """TEMPORARY SPRINT FIX - May 2026: force-allow when WMATIC ≥ $5.5 and idle 4+ cycles."""
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
    assert "FORCE small profit take | WMATIC=$20.00 healthy_stack, no exit for 4 cycles" in captured
    assert "notional=$3.40" in captured
    assert "bypassing min_notional" in captured
    assert "force_no_exit_cycles" in captured


def test_profit_take_balance_relief_bypass_force_below_standard_p2_floors(capsys):
    """TEMPORARY SPRINT FIX - May 2026: force path bypasses $7 wm / $2 notional / weak signal."""
    state: dict = {}
    for _ in range(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN):
        _profit_take_bump_cycle_counter(state)
    notional = 1.9
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(notional * 1_000_000_000_000_000_000),
        signal_strength=0.20,
    )
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=Balances(usdt=10.0, wmatic=6.8, pol=1.0, usdc=30.0),
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "HOLD"},
        state=state,
    )
    captured = capsys.readouterr().out
    assert "FORCE small profit take | WMATIC=$6.80 low_stack, no exit for 4 cycles" in captured
    assert f"notional=${notional:.2f}" in captured
    assert "bypassing min_notional" in captured
    assert "force_no_exit_cycles" in captured


def test_profit_take_balance_relief_bypass_force_at_observed_wmatic_range(capsys):
    """TEMPORARY SPRINT: full bypass path when WMATIC ~$5.7 and idle 4+ cycles."""
    state: dict = {}
    for _ in range(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN):
        _profit_take_bump_cycle_counter(state)
    notional = 1.9
    wmatic_usd = 5.7
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(notional * 1_000_000_000_000_000_000),
        signal_strength=0.20,
    )
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=Balances(usdt=10.0, wmatic=wmatic_usd, pol=1.0, usdc=30.0),
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "HOLD"},
        state=state,
    )
    captured = capsys.readouterr().out
    assert f"FORCE small profit take | WMATIC=${wmatic_usd:.2f} low_stack" in captured
    assert "bypassing min_notional" in captured
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


def test_profit_take_balance_relief_bypass_rejects_sub_two_dollar_wmatic_stack():
    """Signal-Driven Rotation: low-WMATIC P2 still needs ≥ $2 stack."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(8 * 1_000_000_000_000_000_000),
        signal_strength=0.80,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=1.5, pol=1.0)
    assert not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
    )


def test_profit_take_balance_relief_bypass_accepts_low_wmatic_stack_below_seven(capsys):
    """Signal-Driven Rotation: $5.50 WMATIC stack passes relaxed P2 wm floor ($2)."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(2.5 * 1_000_000_000_000_000_000),
        signal_strength=0.50,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=5.5, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "TP_HIT", "gain_pct": 3.0},
    )
    captured = capsys.readouterr().out
    assert "allowed=True" in captured
    assert "wm=$5.50" in captured


def test_profit_take_wmatic_stack_low_boundary():
    assert _profit_take_wmatic_stack_low(6.99)
    assert not _profit_take_wmatic_stack_low(7.0)


def test_profit_take_force_small_relief_low_wmatic_three_cycles():
    assert _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=5.5,
        notional_usd=_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD,
        cycles_since_exit=_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN,
    )
    assert not _profit_take_force_small_relief_eligible(
        direction="WMATIC_TO_USDT",
        wm_equiv_usd=_MAIN_STRATEGY_LOW_WMATIC_FORCE_WM_MIN_USD - 0.01,
        notional_usd=_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD,
        cycles_since_exit=_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN,
    )


def test_profit_take_balance_relief_signal_strength_low_wmatic_floor():
    decision = TradeDecision(direction="WMATIC_TO_USDT", amount_in=1, signal_strength=0.40)
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        {"reason": "TP_HIT", "gain_pct": 1.0},
        wmatic_usd_equiv=5.0,
    )
    assert strength >= _MAIN_STRATEGY_LOW_WMATIC_P2_SIGNAL_MIN


def test_main_strategy_stable_rotation_fallback_requires_cycles(monkeypatch):
    state: dict = {"profit_take_rotation": {"cycles_since_exit": 2}}
    balances = Balances(usdt=40.0, usdc=30.0, wmatic=5.0, pol=1.0)
    monkeypatch.setattr(
        "modules.swap_executor._facade",
        lambda: type("C", (), {"ENABLE_X_SIGNAL_EQUITY": True})(),
    )
    assert _main_strategy_stable_rotation_fallback(balances, 1.0, state=state) is None


def test_main_strategy_stable_rotation_fallback_returns_xsignal_buy(monkeypatch):
    state: dict = {
        "profit_take_rotation": {
            "cycles_since_exit": _MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_CYCLES_MIN,
        }
    }
    balances = Balances(usdt=40.0, usdc=30.0, wmatic=5.0, pol=1.0)
    expected = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=8_000_000,
        trade_size=8.0,
        signal_strength=0.80,
        message="fallback buy",
    )

    class _Facade:
        ENABLE_X_SIGNAL_EQUITY = True

    monkeypatch.setattr("modules.swap_executor._facade", lambda: _Facade())
    monkeypatch.setattr(
        "modules.swap_executor.cs_try_x_signal_equity_decision",
        lambda *_a, **_k: expected,
    )
    got = _main_strategy_stable_rotation_fallback(balances, 1.0, state=state)
    assert got is expected


def test_main_strategy_stable_rotation_fallback_low_wmatic_relaxed_signal(monkeypatch):
    """Low WMATIC stack uses relaxed stable fallback signal floor (0.65)."""
    state: dict = {
        "profit_take_rotation": {
            "cycles_since_exit": _MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_CYCLES_MIN,
        }
    }
    balances = Balances(usdt=40.0, usdc=30.0, wmatic=5.0, pol=1.0)
    moderate = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=8_000_000,
        trade_size=8.0,
        signal_strength=_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_SIGNAL,
        message="low wm fallback",
    )

    class _Facade:
        ENABLE_X_SIGNAL_EQUITY = True

    monkeypatch.setattr("modules.swap_executor._facade", lambda: _Facade())
    monkeypatch.setattr(
        "modules.swap_executor.cs_try_x_signal_equity_decision",
        lambda *_a, **_k: moderate,
    )
    got = _main_strategy_stable_rotation_fallback(balances, 1.0, state=state)
    assert got is moderate


def test_main_strategy_stable_rotation_fallback_rejects_weak_signal(monkeypatch):
    state: dict = {
        "profit_take_rotation": {
            "cycles_since_exit": _MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_CYCLES_MIN,
        }
    }
    balances = Balances(usdt=40.0, usdc=30.0, wmatic=5.0, pol=1.0)
    weak = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=8_000_000,
        trade_size=8.0,
        signal_strength=_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_SIGNAL - 0.05,
    )

    class _Facade:
        ENABLE_X_SIGNAL_EQUITY = True

    monkeypatch.setattr("modules.swap_executor._facade", lambda: _Facade())
    monkeypatch.setattr(
        "modules.swap_executor.cs_try_x_signal_equity_decision",
        lambda *_a, **_k: weak,
    )
    assert _main_strategy_stable_rotation_fallback(balances, 1.0, state=state) is None


def test_main_strategy_idle_rotation_sell_after_low_wmatic_idle_cycles():
    state: dict = {}
    for _ in range(_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN):
        _profit_take_bump_cycle_counter(state)
    balances = Balances(usdt=80.0, usdc=30.0, wmatic=5.7, pol=1.0)
    decision = _main_strategy_idle_rotation_sell_decision(balances, 1.0, state=state)
    assert decision is not None
    assert decision.direction == "WMATIC_TO_USDT"
    assert decision.amount_in == int(5.7 * 0.32 * 1e18)


def test_main_strategy_idle_rotation_sell_not_before_cycle_threshold():
    state: dict = {}
    _profit_take_bump_cycle_counter(state)
    balances = Balances(usdt=80.0, usdc=30.0, wmatic=5.7, pol=1.0)
    assert _main_strategy_idle_rotation_sell_decision(balances, 1.0, state=state) is None
    eligible, note = _main_strategy_idle_rotation_eligibility(balances, 1.0, state)
    assert not eligible
    assert "idle_cycles=1/3" in note


def test_profit_take_balance_relief_bypass_accepts_notional_at_relaxed_floor(capsys):
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(2.0 * 1_000_000_000_000_000_000),
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
    assert "notional=$2.00" in captured
    assert "allowed=True" in captured


def test_profit_take_balance_relief_bypass_accepts_observed_two_usd_notional(capsys):
    """TEMPORARY sprint (May 2026): ~$2.05 profit-take sizes pass at $2.0 floor."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(2.05 * 1_000_000_000_000_000_000),
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
    assert "notional=$2.05" in captured
    assert "allowed=True" in captured


def test_profit_take_balance_relief_bypass_accepts_observed_sub_three_notional(capsys):
    """TEMPORARY sprint (May 2026): ~$2.88 profit-take sizes pass at $2.0 floor."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(2.88 * 1_000_000_000_000_000_000),
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
    assert "notional=$2.88" in captured
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


def test_profit_take_balance_relief_bypass_allows_hold_on_low_wmatic_stack(capsys):
    """Signal-Driven Rotation: HOLD ignored for scoring when stack < $7 (small rotation)."""
    decision = TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(2.5 * 1_000_000_000_000_000_000),
        signal_strength=0.90,
    )
    balances = Balances(usdt=10.0, usdc=30.0, wmatic=6.0, pol=1.0)
    assert _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=1.0,
        min_trade_usd=10.0,
        profit_signal={"reason": "HOLD"},
    )
    captured = capsys.readouterr().out
    assert "allowed=True" in captured


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
        amount_in=11_000_000,
        trade_size=11.0,
        signal_strength=0.90,
    )
    # Dynamic effective gate is $12 at |signal|>=0.85; $11 must not get gated slippage.
    assert _x_signal_gated_trade_relaxed_slippage(decision, decision_notional_usd=11.0) is None


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
    assert resolved[2] == 125


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
    assert resolved[0:2] == (8000, 10000)
    assert resolved[2] is not None and resolved[2] >= 50


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


def test_x_signal_stf_pause_blocks_buy_after_threshold(monkeypatch):
    monkeypatch.setattr("modules.swap_executor.cfg.X_SIGNAL_STF_PAUSE_AFTER_FAILURES", 2)
    monkeypatch.setattr("modules.swap_executor.cfg.X_SIGNAL_STF_PAUSE_SECONDS", 600)
    state: dict = {}
    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=12_000_000,
        signal_strength=0.92,
        cooldown_asset=("WETH_ALPHA", 1800),
    )
    _record_x_signal_stf_failure(state, decision, {"stf": True, "revert_reason": "STF"})
    _record_x_signal_stf_failure(state, decision, {"stf": True, "revert_reason": "STF"})
    paused, detail = _x_signal_stf_pause_active(state, "WETH_ALPHA")
    assert paused is True
    assert "stf_pause_active" in detail
    filtered = _x_signal_apply_stf_pause_filter(decision, state=state)
    assert filtered is None


def test_x_signal_stf_pause_clears_after_success_path():
    state = {
        "x_signal_stf_backoff": {
            "WETH_ALPHA": {"failures": 1, "paused_until": time.time() + 500},
        }
    }
    from modules.swap_executor import _clear_x_signal_stf_pause

    decision = TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=12_000_000,
        cooldown_asset=("WETH_ALPHA", 1800),
    )
    _clear_x_signal_stf_pause(state, decision)
    assert "WETH_ALPHA" not in state.get("x_signal_stf_backoff", {})


def test_x_signal_equity_effective_dust_min_requires_healthy_stables(monkeypatch):
    monkeypatch.setattr("modules.swap_executor._facade", lambda: __import__("clean_swap"))
    monkeypatch.setattr("clean_swap.MIN_TRADE_USD", 15.0)
    monkeypatch.setattr("clean_swap.X_SIGNAL_EQUITY_DUST_MIN_USD", 7.5)
    b_low = Balances(usdt=10.0, usdc=60.0, wmatic=0.0, pol=0.0)
    assert _x_signal_equity_effective_dust_min(b_low) is None
    b_ok = Balances(usdt=50.0, usdc=50.0, wmatic=0.0, pol=0.0)
    assert _x_signal_equity_effective_dust_min(b_ok) == pytest.approx(7.5)


def test_min_net_edge_floor_pct_defaults_to_module_constant(monkeypatch):
    monkeypatch.delattr("modules.swap_executor.cfg", "MIN_NET_EDGE_PCT", raising=False)
    assert _min_net_edge_floor_pct() == pytest.approx(_MIN_NET_EDGE_PCT)


def test_min_net_edge_floor_pct_uses_config_when_set(monkeypatch):
    monkeypatch.setattr("modules.swap_executor.cfg.MIN_NET_EDGE_PCT", 2.5)
    assert _min_net_edge_floor_pct() == pytest.approx(2.5)


def test_estimate_expected_net_edge_pct_subtracts_gas_from_gross():
    net = estimate_expected_net_edge_pct(
        trade_usd=20.0,
        expected_gross_edge_pct=5.0,
        gas_cost_usd=0.20,
    )
    assert net == pytest.approx(4.0)


def test_infer_expected_gross_edge_pct_scales_x_signal_by_strength(monkeypatch):
    monkeypatch.setattr("modules.swap_executor.cfg.env_float", lambda _k, default: 12.0)
    weak = TradeDecision(direction="USDC_TO_EQUITY", signal_strength=0.65)
    strong = TradeDecision(direction="USDC_TO_EQUITY", signal_strength=0.95)
    assert _infer_expected_gross_edge_pct(weak) == pytest.approx(3.0)
    assert _infer_expected_gross_edge_pct(strong) == pytest.approx(10.5)


def test_trade_passes_min_net_edge_respects_env_floor(monkeypatch):
    monkeypatch.setattr("modules.swap_executor.cfg.POL_USD_PRICE", 0.5)
    monkeypatch.setattr("modules.swap_executor.cfg.MIN_NET_EDGE_PCT", 50.0)
    d = TradeDecision(direction="USDT_TO_WMATIC", trade_size=20.0)
    passes, _net = trade_passes_min_net_edge(d, trade_usd=20.0, gas_gwei=40.0)
    assert not passes


def test_trade_passes_min_net_edge_rejects_small_weak_x_signal(monkeypatch):
    monkeypatch.setattr("modules.swap_executor.cfg.POL_USD_PRICE", 0.5)
    d = TradeDecision(direction="USDC_TO_EQUITY", trade_size=5.0, signal_strength=0.62)
    passes, net = trade_passes_min_net_edge(d, trade_usd=5.0, gas_gwei=2500.0)
    assert not passes
    assert net < MIN_NET_EDGE_PCT


def test_trade_passes_min_net_edge_allows_main_strategy_buy(monkeypatch):
    monkeypatch.setattr("modules.swap_executor.cfg.POL_USD_PRICE", 0.5)
    monkeypatch.setattr("modules.swap_executor.cfg.TAKE_PROFIT_PCT", 5.0)
    d = TradeDecision(direction="USDT_TO_WMATIC", trade_size=15.0)
    passes, net = trade_passes_min_net_edge(d, trade_usd=15.0, gas_gwei=40.0)
    assert passes
    assert net >= MIN_NET_EDGE_PCT


def test_trade_passes_min_net_edge_skips_exits():
    d = TradeDecision(direction="WMATIC_TO_USDT", trade_size=12.0)
    passes, net = trade_passes_min_net_edge(d, trade_usd=12.0, gas_gwei=900.0)
    assert passes
    assert net == 0.0


def test_reject_if_low_expected_net_edge_logs_and_returns_true(monkeypatch, capsys):
    monkeypatch.setattr("modules.swap_executor.cfg.POL_USD_PRICE", 0.5)
    skipped: list[str] = []

    def _log(msg: str) -> None:
        skipped.append(msg)

    d = TradeDecision(direction="USDC_TO_EQUITY", trade_size=5.0, signal_strength=0.62)
    assert _reject_if_low_expected_net_edge(
        d,
        trade_usd=5.0,
        gas_gwei=2500.0,
        log_skip=_log,
    )
    assert skipped and "low_expected_edge" in skipped[0]
    assert "after gas" in skipped[0]
    out = capsys.readouterr().out
    assert "[nanoclaw] Low edge rejected | direction=USDC_TO_EQUITY" in out
    assert "expected_net=" in out
    assert "reason=below_min_net_edge" in out
    assert "stage=planning" in out


def test_reject_if_low_expected_net_edge_fails_closed_missing_notional(capsys):
    skipped: list[str] = []

    def _log(msg: str) -> None:
        skipped.append(msg)

    d = TradeDecision(direction="USDT_TO_WMATIC")
    assert _reject_if_low_expected_net_edge(
        d,
        trade_usd=None,
        gas_gwei=80.0,
        log_skip=_log,
    )
    assert skipped and "missing_notional" in skipped[0]
    out = capsys.readouterr().out
    assert "notional=n/a" in out


def test_log_min_net_edge_policy_once_emits_single_banner(capsys):
    swap_exec_mod._MIN_NET_EDGE_POLICY_LOGGED = False
    _log_min_net_edge_policy_once(stage="planning")
    _log_min_net_edge_policy_once(stage="planning")
    out = capsys.readouterr().out
    assert out.count("MIN_NET_EDGE_ACTIVE") == 1
    assert "floor=" in out
    assert "planning_gas=" in out
