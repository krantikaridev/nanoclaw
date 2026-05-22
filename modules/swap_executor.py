"""Orchestration: precedence, USDC-copy async wrapper, asyncio ``main``."""

from __future__ import annotations

import asyncio
import importlib
import time
from dataclasses import replace
from typing import Callable, Optional

import config as cfg
from config import (
    COPY_TRADE_AGGRESSIVE_THRESHOLD,
    MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE,
    MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION,
    MAIN_STRATEGY_CUT_LOSS_WMATIC_USD,
    MAIN_STRATEGY_MIN_USDT_RESERVE,
    MAIN_STRATEGY_RESERVE_SELL_FRACTION,
    MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD,
)
from nanoclaw.strategies.signal_equity_trader import (
    _X_SIGNAL_MIN_EFFECTIVE_TRADE_USD,
    _X_SIGNAL_MIN_SIZE_OVERRIDE,
)
from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from swap_executor import approve_and_swap

from external_layer.control import CycleControlSnapshot, load_cycle_control

from modules import attribution
from modules import wallet_performance
from modules import signal as signal_module
from protection import record_buy

from . import runtime
from .runtime import (
    Balances,
    TradeDecision,
    USDC_COPY_STRATEGY,
    is_copy_trading_enabled,
    w3,
)

_DEFENSIVE_PAUSE_CYCLES = 3

# Entry directions blocked when ``control.json`` has ``paused: true`` (protection exits still run).
_CONTROL_PAUSE_BLOCK_ENTRIES = frozenset({"USDT_TO_WMATIC", "USDC_TO_WMATIC", "USDC_TO_EQUITY"})

# v1 minimum quality filter — first step toward rejecting low-edge entries after gas/fees.
# Floor from env ``MIN_NET_EDGE_PCT`` (see config.py / .env.example); future learning can tune from history.
_MIN_NET_EDGE_ENTRY_DIRECTIONS = frozenset({"USDC_TO_EQUITY", "USDT_TO_WMATIC"})
_EST_SWAP_GAS_UNITS = 180_000.0


def _estimate_swap_gas_cost_usd(gas_gwei: float) -> float:
    """Rough Polygon ERC-20 swap gas cost in USD (matches signal_equity_trader estimate)."""
    pol_price_usd = max(0.0, float(getattr(cfg, "POL_USD_PRICE", 0.0)))
    return max(0.0, (float(gas_gwei) * _EST_SWAP_GAS_UNITS / 1_000_000_000.0) * pol_price_usd)


def _infer_expected_gross_edge_pct(decision: TradeDecision) -> float:
    """Conservative gross upside % before gas — v1 heuristic, not a live quote."""
    direction = str(decision.direction or "").strip().upper()
    if direction == "USDC_TO_EQUITY":
        strong_tp = float(cfg.env_float("X_SIGNAL_EQUITY_STRONG_TP_PCT", 12.0))
        strength = decision.signal_strength
        if strength is not None and float(strength) > 0:
            s = abs(float(strength))
            if s < 0.6:
                scale = 0.25
            else:
                scale = max(0.25, min(1.0, (s - 0.6) / 0.4))
            return max(strong_tp * 0.25, strong_tp * scale)
        return max(0.0, strong_tp)
    if direction == "USDT_TO_WMATIC":
        return max(0.0, float(getattr(cfg, "TAKE_PROFIT_PCT", 5.0)))
    return 0.0


def estimate_expected_net_edge_pct(
    *,
    trade_usd: float,
    expected_gross_edge_pct: float,
    gas_cost_usd: float,
) -> float:
    """Net expected return % of notional after subtracting estimated gas from gross edge."""
    notional = float(trade_usd)
    if notional <= 0.0:
        return -100.0
    gross_profit_usd = notional * (float(expected_gross_edge_pct) / 100.0)
    net_profit_usd = gross_profit_usd - max(0.0, float(gas_cost_usd))
    return (net_profit_usd / notional) * 100.0


def trade_passes_min_net_edge(
    decision: TradeDecision,
    *,
    trade_usd: float,
    gas_gwei: float,
    min_net_edge_pct: float | None = None,
) -> tuple[bool, float]:
    """Return (passes, expected_net_pct) for X-Signal and main-strategy entry directions."""
    direction = str(decision.direction or "").strip().upper()
    if direction not in _MIN_NET_EDGE_ENTRY_DIRECTIONS:
        return True, 0.0
    gross_pct = _infer_expected_gross_edge_pct(decision)
    gas_usd = _estimate_swap_gas_cost_usd(float(gas_gwei))
    expected_net = estimate_expected_net_edge_pct(
        trade_usd=float(trade_usd),
        expected_gross_edge_pct=gross_pct,
        gas_cost_usd=gas_usd,
    )
    floor = float(
        getattr(cfg, "MIN_NET_EDGE_PCT", 1.75) if min_net_edge_pct is None else min_net_edge_pct
    )
    return expected_net + 1e-9 >= floor, expected_net


def _reject_if_low_expected_net_edge(
    decision: TradeDecision,
    *,
    trade_usd: float | None,
    gas_gwei: float,
    log_skip: Callable[[str], None],
) -> bool:
    """Log and return True when the entry should be blocked for low expected net edge."""
    if trade_usd is None:
        return False
    passes, expected_net = trade_passes_min_net_edge(
        decision,
        trade_usd=float(trade_usd),
        gas_gwei=float(gas_gwei),
    )
    if passes:
        return False
    min_floor = float(getattr(cfg, "MIN_NET_EDGE_PCT", 1.75))
    log_skip(
        f"low_expected_edge (expected_net={expected_net:.2f}% < {min_floor:.2f}%)"
    )
    print(f"[nanoclaw] Trade rejected | Low edge | expected_net={expected_net:.2f}%")
    return True


def _usdc_copy_strategy_with_pct(strategy: USDCopyStrategy, pct: float) -> USDCopyStrategy:
    """Clone USDC-copy strategy with an alternate ``copy_trade_pct`` for this cycle only."""
    pf = float(pct)
    cfg_obj = getattr(strategy, "config", None)
    try:
        cur = float(getattr(cfg_obj, "copy_trade_pct", pf)) if cfg_obj is not None else pf
    except (TypeError, ValueError):
        cur = pf
    if abs(cur - pf) < 1e-12:
        return strategy
    # Only real ``USDCopyStrategy`` instances expose a frozen ``USDCopyConfig`` + gas_protector.
    return USDCopyStrategy(
        config=replace(strategy.config, copy_trade_pct=pf),
        gas_protector=strategy.gas_protector,
    )


def _cycle_risk_level(balances: Balances) -> str:
    """
    Single-cycle risk classification used for defensive entry gating.

    Keep consistent with X-signal risk heuristics (USDT/WMATIC liquidity risk).
    """
    try:
        return str(
            signal_module._x_signal_buy_risk_level(
                usdt=float(balances.usdt),
                wmatic=float(balances.wmatic),
            )
        ).strip().upper()
    except Exception:
        return "LOW"


def _defensive_pause_state(state: dict, *, risk_level: str) -> tuple[bool, int]:
    """
    Track sustained HIGH risk and trigger a temporary pause for new entries.

    Rules:
    - Count consecutive cycles at HIGH.
    - When HIGH persists for 2+ cycles, enter a short defensive pause window.
    - Clear immediately when risk drops to MEDIUM/LOW.
    """
    d = state.setdefault("defensive_pause", {})
    high_streak = int(d.get("high_streak", 0) or 0)
    remaining = int(d.get("remaining_cycles", 0) or 0)

    rl = str(risk_level or "").strip().upper()
    if rl != "HIGH":
        if remaining > 0 or high_streak > 0:
            print(f"{runtime._nanolog()}Defensive pause cleared (risk={rl})")
        d["high_streak"] = 0
        d["remaining_cycles"] = 0
        return False, 0

    # HIGH risk
    high_streak += 1
    d["high_streak"] = high_streak

    entered = False
    if high_streak >= 2 and remaining <= 0:
        remaining = int(_DEFENSIVE_PAUSE_CYCLES)
        entered = True

    active = bool(remaining > 0 and high_streak >= 2)
    if active:
        if entered:
            print(
                f"{runtime._nanolog()}🚨 HIGH RISK sustained → Entering temporary defensive pause to protect PnL"
            )
        d["remaining_cycles"] = max(0, remaining - 1)
        return True, int(d["remaining_cycles"])

    d["remaining_cycles"] = 0
    return False, 0


def _facade():
    """Tests monkeypatch attrs on ``clean_swap`` — always read knobs from that module."""
    return importlib.import_module("clean_swap")


def cs_check_exit_conditions() -> tuple[bool, str | None]:
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.check_exit_conditions()


def cs_evaluate_take_profit(current_price: float, state: dict):
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.evaluate_take_profit(current_price, state)


def cs_try_x_signal_equity_decision(balances: Balances, *, dry_run: bool = False):
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.try_x_signal_equity_decision(balances, dry_run=dry_run)


def cs_build_protection_exit_decision(
    reason: str,
    current_price: float,
    wmatic_balance: float,
    open_trade: Optional[dict],
) -> TradeDecision:
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.build_protection_exit_decision(
        reason=reason or "UNKNOWN",
        current_price=current_price,
        wmatic_balance=wmatic_balance,
        open_trade=open_trade,
    )


def cs_build_profit_exit_decision(profit_signal: dict, wmatic_balance: float) -> TradeDecision:
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.build_profit_exit_decision(profit_signal, wmatic_balance)


def cs_get_latest_open_trade(trade_log_file: str | None = None):
    clean_swap = importlib.import_module("clean_swap")
    if trade_log_file is None:
        return clean_swap.get_latest_open_trade()
    return clean_swap.get_latest_open_trade(trade_log_file)


def select_copy_trade(
    balances: Balances,
    wallets: list[str],
    *,
    copy_trade_pct: float | None = None,
) -> TradeDecision:
    cs = _facade()
    active_wallets = [wallet for wallet in wallets if cs.can_trade_wallet(wallet)]
    if not active_wallets:
        cs._log_trade_skipped(f"cooldown (all wallets in {cs.PER_WALLET_COOLDOWN}s window)")
        return TradeDecision(message=f"TRADE SKIPPED: cooldown (all wallets in {cs.PER_WALLET_COOLDOWN}s window)")

    # FIXED SIZING: $12–$20 per signal (bug fix 2026-05-03); spend USDT leg only
    pct = float(cs.COPY_TRADE_PCT) if copy_trade_pct is None else float(copy_trade_pct)
    trade_size = cs.fixed_copy_trade_usd(balances.usdc, balances.usdt, pct)
    trade_size = min(trade_size, balances.usdt)
    return TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message="🔄 REAL POLYCOPY MODE (28%) - Monitoring live wallets",
    )


async def evaluate_usdc_copy_trade(
    balances: Balances,
    wallets: list[str],
    *,
    strategy: Optional[USDCopyStrategy] = None,
) -> TradeDecision:
    cs = _facade()
    if not cs.ENABLE_USDC_COPY:
        return TradeDecision(message="ℹ️ USDC copy disabled")

    usdc_strategy = strategy if strategy is not None else USDC_COPY_STRATEGY
    plan = usdc_strategy.build_plan(
        usdc_balance=balances.usdc,
        usdt_balance=balances.usdt,
        wallets=wallets,
        wallet_address_for_gas=cs.WALLET,
        can_trade_wallet=cs.can_trade_wallet,
    )
    if not plan:
        return TradeDecision(message="ℹ️ No USDC-copy trade this cycle")

    cw = (
        str(plan.wallet).strip(),
        int(usdc_strategy.config.per_wallet_cooldown_seconds),
    ) if plan.wallet else None
    return TradeDecision(
        direction="USDC_TO_WMATIC",
        amount_in=plan.amount_in,
        trade_size=plan.trade_size,
        message=plan.message,
        cooldown_wallet=cw,
    )

def select_main_strategy_trade(
    balances: Balances,
    current_price: float,
) -> TradeDecision:
    cs = _facade()
    # FIXED SIZING: $12–$20 per signal (bug fix 2026-05-03)
    trade_size = cs.fixed_copy_trade_usd(balances.usdc, balances.usdt, cs.COPY_TRADE_PCT)
    trade_size = min(trade_size, balances.usdt)
    wmatic_value_usd = balances.wmatic * current_price

    # Signal-Driven Rotation (May 2026): do not lock USDT into WMATIC when rotation-priority X BUY is live.
    rotation_buy = getattr(
        cs, "_rotation_priority_buy_present", signal_module.rotation_priority_detector
    )
    if (
        bool(getattr(cs, "ENABLE_X_SIGNAL_EQUITY", False))
        and bool(rotation_buy())
        and balances.usdt >= MAIN_STRATEGY_MIN_USDT_RESERVE
        and MAIN_STRATEGY_CUT_LOSS_WMATIC_USD < wmatic_value_usd < MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD
    ):
        print(
            f"{runtime._nanolog()}Signal-Driven Rotation: deferring USDT→WMATIC — "
            "strong external X-Signal BUY takes capital priority over WMATIC accumulation"
        )
        return TradeDecision(
            message="ℹ️ Main WMATIC buy deferred (strong X-Signal BUY — Signal-Driven Rotation)"
        )

    if balances.usdt < MAIN_STRATEGY_MIN_USDT_RESERVE:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_RESERVE_SELL_FRACTION * 1e18),
            message=(
                f"🔄 USDT RESERVE PROTECTION: ${balances.usdt:.2f} < $"
                f"{MAIN_STRATEGY_MIN_USDT_RESERVE:.0f}"
            ),
        )

    if wmatic_value_usd > MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_RESERVE_SELL_FRACTION * 1e18),
            message=f"🔄 Taking profit (WMATIC high: ${wmatic_value_usd:.2f})",
        )

    if wmatic_value_usd < MAIN_STRATEGY_CUT_LOSS_WMATIC_USD and balances.wmatic > MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION * 1e18),
            message=f"🔄 Cutting loss (WMATIC down: ${wmatic_value_usd:.2f})",
        )

    return TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message=f"🔄 Buying WMATIC (hold preferred) | Size: ${trade_size:.2f}",
    )


def _decision_notional_usd(decision: TradeDecision, *, current_price_usd: float = 0.0) -> Optional[float]:
    if float(decision.trade_size or 0.0) > 0:
        return float(decision.trade_size)

    # Stable-coin input directions are denominated in 6-decimal USD units.
    stable_in_directions = {
        "USDT_TO_WMATIC",
        "USDT_TO_USDC",
        "USDC_TO_WMATIC",
        "USDC_TO_EQUITY",
    }
    if str(decision.direction or "").strip().upper() in stable_in_directions and int(decision.amount_in or 0) > 0:
        return float(decision.amount_in) / 1_000_000.0

    # WMATIC input directions are denominated in 18-decimal wei.
    # Convert token amount -> USD notional with the current WMATIC price.
    wmatic_in_directions = {
        "WMATIC_TO_USDT",
        "WMATIC_TO_USDC",
    }
    if (
        str(decision.direction or "").strip().upper() in wmatic_in_directions
        and int(decision.amount_in or 0) > 0
        and float(current_price_usd or 0.0) > 0.0
    ):
        return (float(decision.amount_in) / 1_000_000_000_000_000_000.0) * float(current_price_usd)
    return None


def _defer_if_dust(
    decision: TradeDecision,
    *,
    branch_name: str,
    current_price_usd: float,
    min_trade_usd: float | None = None,
) -> bool:
    """Return True when branch decision is below the effective min notional and should fall through.

    ``min_trade_usd`` overrides ``clean_swap.MIN_TRADE_USD`` when set (used for X-SIGNAL-only dust).
    """
    cs = _facade()
    eff_min = (
        float(min_trade_usd)
        if min_trade_usd is not None
        else float(getattr(cs, "MIN_TRADE_USD", 0.0) or 0.0)
    )
    if eff_min <= 0:
        return False
    notional_usd = _decision_notional_usd(decision, current_price_usd=current_price_usd)
    if notional_usd is None or notional_usd + 1e-9 >= eff_min:
        return False

    reason_txt = (
        f"{branch_name.lower()}_dust_deferred "
        f"({decision.direction}: ${notional_usd:.2f} < min_notional_usd ${eff_min:.2f})"
    )
    cs._log_trade_skipped(reason_txt)
    print(
        f"{runtime._nanolog()}{branch_name} DUST DEFER | "
        f"direction={decision.direction} | size=${notional_usd:.2f} | min=${eff_min:.2f} | "
        "continuing to next strategy"
    )
    return True


# TEMPORARY SPRINT FIX - May 2026: P2 profit-take relief for capital rotation.
# Small WMATIC→stable exits (~$3.38–$3.99) were hard-blocked by MIN_TRADE_USD / dust defer
# (`main_strategy_dust_deferred`) even when the stack was healthy. Revert after sprint window.
_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN = 7.0
# Temporary aggressive floor for sprint - lowered to $2.0 to allow currently observed small profit takes (~$2.05)
_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_NOTIONAL_FLOOR_USD = 2.0
_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH = 0.55
_PROFIT_TAKE_P2_RELIEF_LOG = "[nanoclaw] Main strategy small profit take allowed (P2 relief)"
_PROFIT_TAKE_P2_RELIEF_CHECK_LOG = "[nanoclaw] P2 relief check"
_PROFIT_TAKE_P2_RELIEF_OVERRIDE_ACTIVE_LOG = (
    "[nanoclaw] P2 RELIEF OVERRIDE ACTIVE | WMATIC=${wm} | notional=${notional} | "
    "bypassing min_notional"
)

# TEMPORARY SPRINT FIX - May 2026: keep capital rotation active when profit-take sizes stay
# small and borderline exits would otherwise sit idle for many cycles (revert after sprint).
# TEMPORARY SPRINT: Lowered force threshold to $5.5 so it can activate when WMATIC is in current observed range (~$5.7)
_MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN = 5.5
_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN = 4
_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD = 1.8
_PROFIT_TAKE_FORCE_SMALL_LOG = (
    "[nanoclaw] FORCE small profit take | WMATIC=${wm:.2f} healthy, no exit for {cycles} cycles | "
    "notional=${notional:.2f} | bypassing min_notional"
)

# TEMPORARY (2026-05): small high-conviction X-SIGNAL (~$11) — very high fallback slippage only; easy revert.
_X_SIGNAL_SMALL_HIGH_CONVICTION_MAX_NOTIONAL_USD = 12.0


def _clamp_unit_interval(value: float) -> float:
    """Clamp a numeric score to [0.0, 1.0] for relief signal-strength comparisons."""
    return max(0.0, min(1.0, float(value)))


def _round_relief_signal_strength(value: float) -> float:
    """Return a clamped strength rounded to two decimals for stable comparisons/logging."""
    return round(_clamp_unit_interval(value), 2)


def _profit_take_gain_metric_boost(gain_pct: float, peak_gain_pct: float) -> float:
    """May 2026 sprint (capital rotation): lift strength when realized or peak gains are positive."""
    metric = max(float(gain_pct), float(peak_gain_pct))
    if metric <= 0.0:
        return 0.0
    # +0.04 at ~2% gain, up to +0.12 at ~6%+ (keeps small winners above the relief floor).
    return min(0.12, 0.02 + metric / 50.0)


# May 2026 sprint: floor for standard profit-take reasons so modest gains still clear P2 relief.
_MODERATE_EXIT_REASON_MIN_STRENGTH: dict[str, float] = {
    "STRONG_TP_HIT": 0.65,
    "TRAILING_STOP_HIT": 0.62,
    "TP_HIT": 0.58,
}


def _profit_take_wmatic_stack_strength_boost(
    strength: float,
    wmatic_usd_equiv: float | None,
    wm_min: float,
) -> float:
    """May 2026 sprint (capital rotation): nudge borderline scores when WMATIC stack is healthy."""
    if wmatic_usd_equiv is None:
        return strength
    wm = float(wmatic_usd_equiv)
    if wm > wm_min * 1.5:
        return min(1.0, strength + 0.05)
    if wm > wm_min + 1e-9:
        return min(1.0, strength + 0.03)
    return strength


def _profit_signal_for_relief_scoring(
    profit_signal: dict | None,
    *,
    wmatic_usd_equiv: float | None,
) -> dict | None:
    """TEMPORARY SPRINT FIX - May 2026: HOLD snapshots must not zero relief when stack is healthy."""
    if profit_signal is None:
        return None
    reason = str(profit_signal.get("reason") or "").strip().upper()
    if reason != "HOLD":
        return profit_signal
    wm_min = float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN)
    if wmatic_usd_equiv is not None and float(wmatic_usd_equiv) + 1e-9 >= wm_min:
        return None
    return profit_signal


def _profit_take_apply_healthy_wmatic_signal_floors(
    strength: float,
    *,
    wmatic_usd_equiv: float | None,
    wm_min: float,
    valid_exit_reason: bool,
) -> float:
    # Sprint relaxation: be lenient on signal when WMATIC balance is healthy
    if wmatic_usd_equiv is None or float(wmatic_usd_equiv) + 1e-9 < wm_min:
        return strength
    if valid_exit_reason:
        return max(strength, float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH))
    return strength


def _profit_take_balance_relief_signal_strength(
    decision: TradeDecision,
    profit_signal: dict | None,
    *,
    wmatic_usd_equiv: float | None = None,
) -> float:
    """TEMPORARY SPRINT FIX - May 2026: score P2 profit-take relief exit quality on [0.0, 1.0].

    Prefer profit_signal['signal_strength'] when the strategy supplies it.
    Otherwise derive strength from exit reason and gain/peak/pullback metrics.
    When WMATIC stack ≥ $7 and exit reason is not HOLD, strength is never below 0.55
    (Sprint relaxation: lenient scoring when WMATIC balance is healthy, even on modest gains).
    """
    floor = float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH)
    wm_min = float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN)
    profit_signal = _profit_signal_for_relief_scoring(
        profit_signal,
        wmatic_usd_equiv=wmatic_usd_equiv,
    )

    valid_exit_reason = False
    has_positive_gain = False
    strength = floor

    if profit_signal is not None:
        reason = str(profit_signal.get("reason") or "").strip().upper()
        explicit = profit_signal.get("signal_strength")
        if explicit is not None:
            if reason == "HOLD":
                return 0.0
            strength = _clamp_unit_interval(explicit)
            strength = _profit_take_wmatic_stack_strength_boost(strength, wmatic_usd_equiv, wm_min)
            strength = _profit_take_apply_healthy_wmatic_signal_floors(
                strength,
                wmatic_usd_equiv=wmatic_usd_equiv,
                wm_min=wm_min,
                valid_exit_reason=bool(reason),
            )
            return _round_relief_signal_strength(strength)

        if reason == "HOLD":
            return 0.0

        valid_exit_reason = bool(reason)
        try:
            gain_pct = float(profit_signal.get("gain_pct", 0) or 0)
            peak_gain_pct = float(profit_signal.get("peak_gain_pct", gain_pct) or gain_pct)
            pullback_pct = float(profit_signal.get("pullback_pct", 0) or 0)
        except (TypeError, ValueError):
            gain_pct = peak_gain_pct = pullback_pct = 0.0

        has_positive_gain = gain_pct > 0.0 or peak_gain_pct > 0.0
        gain_boost = _profit_take_gain_metric_boost(gain_pct, peak_gain_pct)

        # May 2026 sprint heuristic tiers when explicit strength is absent.
        if reason == "STRONG_TP_HIT":
            extra = min(0.06, max(0.0, gain_pct - 8.0) / 40.0)
            strength = 0.93 + gain_boost + extra
        elif reason == "TRAILING_STOP_HIT":
            peak_boost = min(0.10, max(0.0, peak_gain_pct) / 35.0)
            trail_boost = min(0.08, max(0.0, pullback_pct) / 12.0)
            strength = 0.84 + peak_boost + trail_boost + gain_boost * 0.5
        elif reason == "TP_HIT":
            metric = max(gain_pct, peak_gain_pct)
            strength = max(floor, 0.62 + metric / 35.0 + gain_boost)
        elif has_positive_gain:
            metric = max(gain_pct, peak_gain_pct)
            strength = max(floor, 0.56 + metric / 45.0 + gain_boost)
        else:
            # Valid exit reason without gain metrics — still worth rotating when stack is healthy.
            strength = floor

        reason_floor = _MODERATE_EXIT_REASON_MIN_STRENGTH.get(reason)
        if reason_floor is not None:
            strength = max(strength, reason_floor)
    elif decision.signal_strength is not None:
        strength = _clamp_unit_interval(decision.signal_strength)
    else:
        strength = floor

    strength = _profit_take_wmatic_stack_strength_boost(strength, wmatic_usd_equiv, wm_min)

    # May 2026 sprint: never round to exactly 0.00 when there is a real exit or positive gain.
    if valid_exit_reason or has_positive_gain:
        strength = max(strength, floor if valid_exit_reason else 0.01)

    strength = _profit_take_apply_healthy_wmatic_signal_floors(
        strength,
        wmatic_usd_equiv=wmatic_usd_equiv,
        wm_min=wm_min,
        valid_exit_reason=valid_exit_reason,
    )
    return _round_relief_signal_strength(strength)


def _profit_take_rotation_state(state: dict | None) -> dict:
    """May 2026 sprint: per-bot counter for cycles since last WMATIC→stable profit exit."""
    if state is None:
        return {}
    return state.setdefault("profit_take_rotation", {})


def _profit_take_cycles_since_exit(state: dict | None) -> int:
    return int(_profit_take_rotation_state(state).get("cycles_since_exit", 0) or 0)


def _profit_take_bump_cycle_counter(state: dict) -> int:
    """Increment once per ``determine_trade_decision`` evaluation (saved with bot state)."""
    d = _profit_take_rotation_state(state)
    cycles = int(d.get("cycles_since_exit", 0) or 0) + 1
    d["cycles_since_exit"] = cycles
    return cycles


def _profit_take_record_exit(state: dict) -> None:
    """Reset rotation counter after a successful WMATIC→stable exit."""
    d = _profit_take_rotation_state(state)
    d["cycles_since_exit"] = 0


def _profit_take_force_small_relief_eligible(
    *,
    direction: str,
    wm_equiv_usd: float,
    notional_usd: float,
    cycles_since_exit: int,
) -> bool:
    """TEMPORARY SPRINT FIX - May 2026: force small profit take when WMATIC ≥ $5.5, idle 4+ cycles."""
    dir_u = str(direction or "").strip().upper()
    if dir_u not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    force_wm_min = float(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN)
    floor_usd = float(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD)
    cycles_min = int(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN)
    if wm_equiv_usd + 1e-9 < force_wm_min:
        return False
    if notional_usd + 1e-9 < floor_usd:
        return False
    return cycles_since_exit >= cycles_min


def _log_profit_take_p2_relief_check(
    *,
    wm_equiv_usd: float | None,
    notional_usd: float | None,
    signal_strength: float | None,
    allowed: bool,
    floor_usd: float | None = None,
    reason: str | None = None,
) -> None:
    """TEMPORARY (48-hour sprint): structured P2 relief decision log for ops triage."""
    wm_s = "n/a" if wm_equiv_usd is None else f"${wm_equiv_usd:.2f}"
    notional_s = "n/a" if notional_usd is None else f"${notional_usd:.2f}"
    signal_s = "n/a" if signal_strength is None else f"{signal_strength:.2f}"
    line = (
        f"{_PROFIT_TAKE_P2_RELIEF_CHECK_LOG} | wm={wm_s} | notional={notional_s} | "
        f"signal={signal_s} | allowed={allowed}"
    )
    if floor_usd is not None:
        line += f" | floor=${floor_usd:.2f}"
    if reason:
        line += f" | reason={reason}"
    print(line)


def _profit_take_balance_relief_bypass_allowed(
    decision: TradeDecision,
    *,
    balances: Balances,
    current_price_usd: float,
    min_trade_usd: float,
    profit_signal: dict | None = None,
    state: dict | None = None,
) -> bool:
    """TEMPORARY (May 2026 sprint): allow small WMATIC→stable profit exits when stack, notional, and signal pass.

    Trade notional may be below ``MIN_TRADE_USD`` as long as total WMATIC USD equivalent is healthy
    (capital rotation — lock small gains back into stables without waiting for a large sell).
    After ``_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN`` cycles without a WMATIC→stable exit, a
    healthy stack (≥ $5.5 WMATIC, notional ≥ $1.8) can force-allow a small take and bypass the
    standard P2 wm/notional/signal gates (still below ``MIN_TRADE_USD``).
    Emits ``[nanoclaw] P2 relief check`` on every WMATIC→stable evaluation (pass/fail + reason).
    """
    direction = str(decision.direction or "").strip().upper()
    if direction not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    eff_min = float(min_trade_usd)
    if eff_min <= 0.0:
        return False
    notional_usd = _decision_notional_usd(decision, current_price_usd=current_price_usd)
    floor_usd = float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_NOTIONAL_FLOOR_USD)
    if notional_usd is None:
        _log_profit_take_p2_relief_check(
            wm_equiv_usd=None,
            notional_usd=None,
            signal_strength=None,
            allowed=False,
            floor_usd=floor_usd,
            reason="no_notional",
        )
        return False
    wm_equiv_usd = float(balances.wmatic) * float(current_price_usd)
    cycles_since_exit = _profit_take_cycles_since_exit(state)
    force_small = _profit_take_force_small_relief_eligible(
        direction=direction,
        wm_equiv_usd=wm_equiv_usd,
        notional_usd=float(notional_usd),
        cycles_since_exit=cycles_since_exit,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        profit_signal,
        wmatic_usd_equiv=wm_equiv_usd,
    )
    allowed = True
    reason: str | None = None
    if notional_usd + 1e-9 >= eff_min:
        allowed = False
        reason = "notional_at_or_above_min_trade"
    elif force_small:
        print(
            _PROFIT_TAKE_FORCE_SMALL_LOG.format(
                wm=wm_equiv_usd,
                cycles=cycles_since_exit,
                notional=float(notional_usd),
            )
        )
        allowed = True
        reason = "force_no_exit_cycles"
    elif notional_usd + 1e-9 < floor_usd:
        allowed = False
        reason = "notional_below_floor"
    elif wm_equiv_usd + 1e-9 < float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN):
        allowed = False
        reason = "wmatic_stack_below_min"
    elif abs(float(strength)) + 1e-9 < float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH):
        allowed = False
        reason = "signal_below_min"
    _log_profit_take_p2_relief_check(
        wm_equiv_usd=wm_equiv_usd,
        notional_usd=notional_usd,
        signal_strength=strength,
        allowed=allowed,
        floor_usd=floor_usd,
        reason=reason,
    )
    return allowed


def _signal_driven_rotation_x_signal_first() -> bool:
    """Signal-Driven Rotation (May 2026): rotation-priority external BUY → X-Signal before WMATIC exits."""
    cs = _facade()
    if not bool(getattr(cs, "ENABLE_X_SIGNAL_EQUITY", False)):
        return False
    detector = getattr(
        cs, "_rotation_priority_buy_present", signal_module.rotation_priority_detector
    )
    return bool(detector())


def _wmatic_stable_p2_relief_override_active(
    decision: TradeDecision,
    *,
    balances: Balances,
    current_price_usd: float,
    min_trade_usd: float,
    profit_signal: dict | None = None,
    state: dict | None = None,
) -> bool:
    """TEMPORARY SPRINT FIX - May 2026: bypass-first P2 relief for WMATIC→stable profit takes.

    Calls ``_profit_take_balance_relief_bypass_allowed()`` before any dust defer or
    ``MIN_TRADE_USD`` gate. When True, caller must return the decision immediately.
    """
    if _signal_driven_rotation_x_signal_first():
        print(
            f"{runtime._nanolog()}Signal-Driven Rotation: P2 WMATIC→stable deferred — "
            "strong X-Signal BUY has cycle priority"
        )
        return False
    direction = str(decision.direction or "").strip().upper()
    if direction not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    if not _profit_take_balance_relief_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=current_price_usd,
        min_trade_usd=min_trade_usd,
        profit_signal=profit_signal,
        state=state,
    ):
        return False
    wm_equiv_usd = float(balances.wmatic) * float(current_price_usd)
    notional_usd = _decision_notional_usd(decision, current_price_usd=current_price_usd)
    notional_s = f"{notional_usd:.2f}" if notional_usd is not None else "?"
    print(
        _PROFIT_TAKE_P2_RELIEF_OVERRIDE_ACTIVE_LOG.format(
            wm=f"{wm_equiv_usd:.2f}",
            notional=notional_s,
        )
    )
    return True


_X_SIGNAL_HIGH_CONVICTION_STRENGTH = 0.85


def _x_signal_small_high_conviction_relaxed_slippage(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> tuple[int, int] | None:
    """TEMPORARY: very high fallback slippage for small USDC→equity X-SIGNAL (>=0.85); easy revert."""
    if str(decision.direction or "").strip().upper() != "USDC_TO_EQUITY":
        return None
    strength = decision.signal_strength
    if strength is None or float(strength) <= 0:
        return None
    if abs(float(strength)) + 1e-9 < _X_SIGNAL_HIGH_CONVICTION_STRENGTH:
        return None
    if decision_notional_usd is None:
        return None
    if decision_notional_usd + 1e-9 > float(_X_SIGNAL_SMALL_HIGH_CONVICTION_MAX_NOTIONAL_USD):
        return None
    return (
        int(cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_PRIMARY_BPS),
        int(cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_RETRY_BPS),
    )


def _x_signal_gated_trade_enhanced_execution_eligible(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> bool:
    """TEMPORARY (48-hour sprint): USDC→equity BUY that passed the $18 effective gate at plan build."""
    if str(decision.direction or "").strip().upper() != "USDC_TO_EQUITY":
        return False
    if bool(getattr(decision, "x_signal_gated_execution", False)):
        return True
    if decision_notional_usd is None:
        return False
    return decision_notional_usd + 1e-9 >= float(_X_SIGNAL_MIN_EFFECTIVE_TRADE_USD)


def _x_signal_gated_trade_relaxed_slippage(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> tuple[int, int] | None:
    """TEMPORARY (48-hour sprint): high fallback slippage for gated X-SIGNAL USDC→equity BUYs."""
    if not _x_signal_gated_trade_enhanced_execution_eligible(
        decision,
        decision_notional_usd=decision_notional_usd,
    ):
        return None
    return (
        int(cfg.X_SIGNAL_GATED_TRADE_FALLBACK_PRIMARY_BPS),
        int(cfg.X_SIGNAL_GATED_TRADE_FALLBACK_RETRY_BPS),
    )


def _resolve_x_signal_enhanced_fallback_execution(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> tuple[int, int, int | None] | None:
    """TEMPORARY (48-hour sprint): (primary_bps, retry_bps, min_out_extra_bps) for X-SIGNAL fallback router."""
    small = _x_signal_small_high_conviction_relaxed_slippage(
        decision,
        decision_notional_usd=decision_notional_usd,
    )
    if small is not None:
        return small[0], small[1], None
    gated = _x_signal_gated_trade_relaxed_slippage(
        decision,
        decision_notional_usd=decision_notional_usd,
    )
    if gated is not None:
        return (
            gated[0],
            gated[1],
            int(cfg.X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS),
        )
    return None


def _x_signal_min_trade_guard_bypass(
    decision: TradeDecision,
    *,
    decision_notional_usd: float,
    min_trade_usd: float,
) -> bool:
    """USDC→equity X-SIGNAL: allow notional in [_X_SIGNAL_MIN_SIZE_OVERRIDE, MIN_TRADE_USD) when highly convicted."""
    if str(decision.direction or "").strip().upper() != "USDC_TO_EQUITY":
        return False
    strength = decision.signal_strength
    if strength is None:
        return False
    s = float(strength)
    if s <= 0 or abs(s) < _X_SIGNAL_HIGH_CONVICTION_STRENGTH:
        return False
    floor = float(_X_SIGNAL_MIN_SIZE_OVERRIDE)
    if decision_notional_usd + 1e-9 < floor:
        return False
    if decision_notional_usd + 1e-9 >= min_trade_usd:
        return False
    return True


def _x_signal_equity_effective_dust_min(balances: Balances) -> float | None:
    """X-SIGNAL-only lower floor when combined stables are healthy; ``None`` → use global ``MIN_TRADE_USD``."""
    cs = _facade()
    base = float(getattr(cs, "MIN_TRADE_USD", 0.0) or 0.0)
    x_floor = float(getattr(cs, "X_SIGNAL_EQUITY_DUST_MIN_USD", 0.0) or 0.0)
    if base <= 0 or x_floor <= 0:
        return None
    stable = float(balances.usdt) + float(balances.usdc)
    # Align with protection / external layer: keep conservative sizing when stables < ~$80.
    if stable < 80.0:
        return None
    return min(base, x_floor)


def determine_trade_decision(
    state: dict,
    balances: Balances,
    current_price: float,
    *,
    dry_run: bool = False,
    cycle_control: CycleControlSnapshot | None = None,
) -> TradeDecision:
    cs = _facade()
    # Operator/agent knobs from repo-root ``control.json``. Production loads via ``load_cycle_control()`` in
    # ``main()`` each cron cycle; unit tests omit ``cycle_control`` → neutral defaults (no disk read).
    ctrl = cycle_control if cycle_control is not None else CycleControlSnapshot()
    entries_paused = bool(ctrl.paused)
    # Copy-trade sizing only (USDT polycopy + USDC copy). Main-strategy buys keep ``COPY_TRADE_PCT`` from env.
    env_pct = float(cs.COPY_TRADE_PCT)
    if ctrl.max_copy_trade_pct is not None:
        effective_copy_pct = float(ctrl.max_copy_trade_pct)
        pct_source = "control.json"
    else:
        effective_copy_pct = env_pct
        pct_source = "env COPY_TRADE_PCT (no max_copy_trade_pct in control.json)"
    print(
        f"[CONTROL] Copy-trade pct={effective_copy_pct:.2f} | source={pct_source} | env COPY_TRADE_PCT={env_pct:.2f}"
    )
    if ctrl.reason:
        print(f"[CONTROL] External layer reason: {ctrl.reason}")
    if entries_paused:
        print("[CONTROL] paused=True → skipping new entry trades (protection exits still allowed)")
    # ``ctrl.force_defensive`` is parsed in ``load_cycle_control`` for future wiring — does not alter protection yet.

    # TEMPORARY (May 2026 sprint): track cycles since last WMATIC→stable profit exit for force-relief.
    _profit_take_bump_cycle_counter(state)

    risk_level = _cycle_risk_level(balances)
    pause_active, pause_remaining = _defensive_pause_state(state, risk_level=risk_level)
    print(
        f"\n{runtime._nanolog()}=== CYCLE {int(time.time())} | BALANCES: USDT=${balances.usdt:.2f} "
        f"USDC=${balances.usdc:.2f} WMATIC=${balances.wmatic:.2f} ==="
    )
    target_wallets_prelude = cs.get_target_wallets()
    print(
        f"🔍 BALANCES | USDT=${balances.usdt:.2f} USDC=${balances.usdc:.2f} "
        f"WMATIC≈{(balances.wmatic * current_price):.2f} USD | POL={balances.pol:.4f} "
        f"| copy_targets={len(target_wallets_prelude)}"
    )
    x_signal_rotation_first = _signal_driven_rotation_x_signal_first()
    print(
        "🔍 DECISION PATH | precedence: PROTECTION → "
        + (
            "X_SIGNAL_EQUITY (rotation-priority BUY — Signal-Driven Rotation) → PROFIT_TAKE → "
            if x_signal_rotation_first
            else "PROFIT_TAKE → X_SIGNAL_EQUITY → "
        )
        + "USDC_COPY | POLYCOPY → MAIN_STRATEGY"
    )
    print(
        f"{runtime._nanolog()}Runtime config | TAKE_PROFIT_PCT={cs.TAKE_PROFIT_PCT:.2f} "
        f"STRONG_SIGNAL_TP={cs.STRONG_SIGNAL_TP:.2f} "
        f"PER_ASSET_COOLDOWN_MINUTES={cs.PER_ASSET_COOLDOWN_MINUTES}"
    )

    if effective_copy_pct >= COPY_TRADE_AGGRESSIVE_THRESHOLD:
        print(f"🔥 AGGRESSIVE MODE ACTIVE | COPY_TRADE_PCT={effective_copy_pct:.2f}")

    should_force_sell, reason = cs_check_exit_conditions()
    if should_force_sell:
        print(f"🔍 DECISION PATH: PROTECTION ({reason})")
        protection_decision = cs_build_protection_exit_decision(
            reason=reason or "UNKNOWN",
            current_price=current_price,
            wmatic_balance=balances.wmatic,
            open_trade=cs_get_latest_open_trade(),
        )
        if not _defer_if_dust(
            protection_decision,
            branch_name="PROTECTION",
            current_price_usd=current_price,
        ):
            return protection_decision

    should_take_profit, profit_signal = cs_evaluate_take_profit(current_price, state)

    def _resolve_x_signal_equity_decision() -> Optional[TradeDecision]:
        if not cs.ENABLE_X_SIGNAL_EQUITY:
            return None
        xd_local = cs_try_x_signal_equity_decision(balances, dry_run=dry_run)
        if (
            pause_active
            and xd_local
            and xd_local.should_execute
            and str(xd_local.direction or "").strip().upper() in {"USDC_TO_EQUITY"}
        ):
            cs._log_trade_skipped(
                f"defensive_pause (risk=HIGH, remaining_cycles={pause_remaining}) — pausing X-signal BUY entries"
            )
            xd_local = None
        xd_dir_local = str(xd_local.direction or "").strip().upper() if xd_local else ""
        if (
            entries_paused
            and xd_local
            and xd_local.should_execute
            and xd_dir_local in _CONTROL_PAUSE_BLOCK_ENTRIES
        ):
            cs._log_trade_skipped("control.json paused=True — skipping X-signal entry trade")
            xd_local = None
        if xd_local and xd_local.should_execute:
            print("🔍 DECISION PATH: X_SIGNAL_EQUITY")
            x_dust_min = _x_signal_equity_effective_dust_min(balances)
            if not _defer_if_dust(
                xd_local,
                branch_name="X_SIGNAL_EQUITY",
                current_price_usd=current_price,
                min_trade_usd=x_dust_min,
            ):
                return xd_local
        return None

    if x_signal_rotation_first:
        xd_early = _resolve_x_signal_equity_decision()
        if xd_early is not None:
            return xd_early
        print(
            f"{runtime._nanolog()}Signal-Driven Rotation: no executable X-Signal plan — "
            "falling through to WMATIC profit-take / main strategy"
        )

    if should_take_profit and profit_signal and balances.wmatic > 0:
        print(f"🔍 DECISION PATH: PROFIT_TAKE ({profit_signal.get('reason','')})")
        profit_decision = cs_build_profit_exit_decision(profit_signal, balances.wmatic)
        eff_pt_min_usd = float(getattr(cs, "MIN_TRADE_USD", 0.0) or 0.0)
        profit_dir = str(profit_decision.direction or "").strip().upper()
        # TEMPORARY SPRINT FIX - May 2026: P2 bypass-first — overrides PROFIT_TAKE dust defer / $10 floor.
        if profit_dir in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
            if _wmatic_stable_p2_relief_override_active(
                profit_decision,
                balances=balances,
                current_price_usd=current_price,
                min_trade_usd=eff_pt_min_usd,
                profit_signal=profit_signal,
                state=state,
            ):
                print(_PROFIT_TAKE_P2_RELIEF_LOG)
                return profit_decision
        if not _defer_if_dust(
            profit_decision,
            branch_name="PROFIT_TAKE",
            current_price_usd=current_price,
        ):
            return profit_decision

    if profit_signal and profit_signal["reason"] == "HOLD":
        print(f"📈 {profit_signal['message']}")

    if not x_signal_rotation_first:
        xd = _resolve_x_signal_equity_decision()
        if xd is not None:
            return xd

    target_wallets = target_wallets_prelude or cs.get_target_wallets()
    if is_copy_trading_enabled() and target_wallets:
        if entries_paused:
            cs._log_trade_skipped("control.json paused=True — skipping copy-trade entries")
        elif pause_active:
            cs._log_trade_skipped(
                f"defensive_pause (risk=HIGH, remaining_cycles={pause_remaining}) — pausing copy-trade entries"
            )
            print(
                f"{runtime._nanolog()}DEFENSIVE PAUSE | blocking copy-trade entries | remaining_cycles={pause_remaining}"
            )
        else:
            if cs.ENABLE_USDC_COPY:
                usdc_strategy = _usdc_copy_strategy_with_pct(USDC_COPY_STRATEGY, effective_copy_pct)
                plan = usdc_strategy.build_plan(
                    usdc_balance=balances.usdc,
                    wallets=target_wallets,
                    wallet_address_for_gas=cs.WALLET,
                    can_trade_wallet=cs.can_trade_wallet,
                    usdt_balance=balances.usdt,
                )
                if plan:  # try all eligible assets
                    print(f"🔍 DECISION PATH: USDC_COPY | Size ~${plan.trade_size:.2f}")
                    print(f"🟦 USDC COPY ACTIVE | Size: ${plan.trade_size:.2f}")
                    cw_usdc = (
                        str(plan.wallet).strip(),
                        int(usdc_strategy.config.per_wallet_cooldown_seconds),
                    ) if plan.wallet else None
                    copy_decision = TradeDecision(
                        direction="USDC_TO_WMATIC",
                        amount_in=plan.amount_in,
                        trade_size=plan.trade_size,
                        message=plan.message,
                        cooldown_wallet=cw_usdc,
                    )
                    if not _defer_if_dust(
                        copy_decision,
                        branch_name="USDC_COPY",
                        current_price_usd=current_price,
                    ):
                        return copy_decision
                    print("🟦 USDC COPY DEFERRED | dust-sized notional, falling through")
                else:
                    print("🟦 USDC COPY ACTIVE | No eligible copy-trade this cycle")
            else:
                print("🔍 DECISION PATH: POLYCOPY_TARGET_WALLETS")
                polycopy_decision = select_copy_trade(
                    balances,
                    target_wallets,
                    copy_trade_pct=effective_copy_pct,
                )
                if not _defer_if_dust(
                    polycopy_decision,
                    branch_name="POLYCOPY",
                    current_price_usd=current_price,
                ):
                    return polycopy_decision

    print(f"🔍 DECISION PATH: MAIN_STRATEGY (WMATIC≈${current_price:.4f})")
    main_decision = select_main_strategy_trade(balances, current_price)
    main_dir = str(main_decision.direction or "").strip().upper()
    eff_main_min_usd = float(getattr(cs, "MIN_TRADE_USD", 0.0) or 0.0)
    # TEMPORARY SPRINT FIX - May 2026: P2 bypass-first — overrides MAIN_STRATEGY dust defer / $10 floor.
    if main_dir in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        if _wmatic_stable_p2_relief_override_active(
            main_decision,
            balances=balances,
            current_price_usd=current_price,
            min_trade_usd=eff_main_min_usd,
            profit_signal=profit_signal,
            state=state,
        ):
            print(_PROFIT_TAKE_P2_RELIEF_LOG)
            return main_decision
    if entries_paused and main_dir in _CONTROL_PAUSE_BLOCK_ENTRIES:
        cs._log_trade_skipped("control.json paused=True — skipping main-strategy entry trade")
        return TradeDecision(message="ℹ️ Paused via control.json (no new entries this cycle)")
    if _defer_if_dust(
        main_decision,
        branch_name="MAIN_STRATEGY",
        current_price_usd=current_price,
    ):
        return TradeDecision(message="ℹ️ Main strategy deferred (dust-sized trade)")
    return main_decision


async def main(*, dry_run: bool = False) -> None:
    cs = _facade()
    if not dry_run:
        try:
            cfg.resolve_private_key(require=True, log_success=True)
        except cfg.MissingPrivateKeyError as exc:
            print(f"{runtime._nanolog()}startup blocked — {exc}")
            return
    print(
        f"{runtime._nanolog()}SECRETS CHECK | All sensitive variables loaded from .env only (not hardcoded)"
    )
    state = cs.load_state()
    balances = cs.get_balances()
    print(f"{runtime._nanolog()}WALLET BALANCE | USDC=${balances.usdc:.2f} | Address={cs.WALLET}")
    _stable = float(balances.usdt) + float(balances.usdc)
    print(
        f"{runtime._nanolog()}WALLET TOTAL USD | TOTAL=${balances.total_portfolio_usd:.2f} "
        f"| USDT=${balances.usdt:.2f} | USDC=${balances.usdc:.2f} | STABLE_USD=${_stable:.2f} "
        f"| WMATIC={balances.wmatic:.6f} "
        f"| POL={balances.pol:.6f} | FE_USD=${balances.followed_equity_usd:.2f}"
    )
    print(
        f"Real USDT: {balances.usdt:.2f} | USDC: {balances.usdc:.2f} | "
        f"WMATIC: {balances.wmatic:.2f} | POL: {balances.pol:.2f}"
    )

    if cs.has_active_lock():
        print("⛔ Lock active — skipping")
        return

    cs.create_lock()
    try:
        current_price = cs.get_live_wmatic_price()
        cs.write_portfolio_history_snapshot(current_price)

        if cs.is_global_cooldown_active(state):
            lr = float(state.get("last_run") or 0.0)
            elapsed_s = max(0.0, time.time() - lr)
            remain_s = max(0.0, cs.COOLDOWN_MINUTES * 60 - elapsed_s)
            print(
                f"{runtime._nanolog()}skip cycle — global cooldown ~{remain_s:.0f}s left "
                f"(COOLDOWN_MINUTES={cs.COOLDOWN_MINUTES}; last_run was {elapsed_s:.0f}s ago)"
            )
            cs._log_trade_skipped(f"cooldown (global, ~{remain_s:.0f}s left)")
            return

        cycle_snapshot = load_cycle_control()
        decision = await asyncio.to_thread(
            lambda snap=cycle_snapshot: determine_trade_decision(
                state,
                balances,
                current_price,
                dry_run=dry_run,
                cycle_control=snap,
            )
        )
        cs.save_state(state)

        if decision.message:
            print(decision.message)

        if not decision.should_execute:
            cs._log_trade_skipped("protection/strategy returned no actionable trade")
            print("ℹ️ No actionable trade this cycle")
            return

        min_trade_usd = float(getattr(cs, "MIN_TRADE_USD", 0.0) or 0.0)
        decision_notional_usd = _decision_notional_usd(decision, current_price_usd=current_price)
        if (
            min_trade_usd > 0
            and decision_notional_usd is not None
            and decision_notional_usd + 1e-9 < min_trade_usd
        ):
            profit_signal_guard: dict | None = None
            if str(decision.direction or "").strip().upper() in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
                should_tp, profit_signal_guard = cs_evaluate_take_profit(current_price, state)
                if not should_tp:
                    profit_signal_guard = None
            if _x_signal_min_trade_guard_bypass(
                decision,
                decision_notional_usd=decision_notional_usd,
                min_trade_usd=min_trade_usd,
            ):
                print("[nanoclaw-av] X-SIGNAL min_trade_guard bypassed (high conviction)")
            elif _profit_take_balance_relief_bypass_allowed(
                decision,
                balances=balances,
                current_price_usd=current_price,
                min_trade_usd=min_trade_usd,
                profit_signal=profit_signal_guard,
                state=state,
            ):
                print(_PROFIT_TAKE_P2_RELIEF_LOG)
            else:
                reason = (
                    f"min_trade_guard ({decision.direction}: ${decision_notional_usd:.2f} "
                    f"< MIN_TRADE_USD ${min_trade_usd:.2f})"
                )
                cs._log_trade_skipped(reason)
                print(
                    f"{runtime._nanolog()}TRADE SKIPPED | below minimum size | "
                    f"direction={decision.direction} | size=${decision_notional_usd:.2f} | min=${min_trade_usd:.2f}"
                )
                return

        gas_status = cs.get_gas_status()
        gas_gwei_edge = float(gas_status.get("gas_gwei") or 0.0)
        if _reject_if_low_expected_net_edge(
            decision,
            trade_usd=decision_notional_usd,
            gas_gwei=gas_gwei_edge,
            log_skip=cs._log_trade_skipped,
        ):
            return

        if dry_run:
            print(f"🧪 DRY RUN: would execute {decision.direction} for amount_in={decision.amount_in}")
            return

        pol_now = float(cs.get_pol_balance())
        if pol_now < float(cs.MIN_POL_FOR_GAS):
            if cs.AUTO_TOPUP_POL:
                topup_ok = await asyncio.to_thread(
                    cs.ensure_pol_for_trade,
                    float(cs.MIN_POL_FOR_GAS),
                )
                if not topup_ok:
                    cs._log_trade_skipped(f"POL low (auto top-up failed; need {cs.MIN_POL_FOR_GAS:.4f})")
                    print(f"{runtime._nanolog()}AUTO-POL failed — trade blocked (pol<{cs.MIN_POL_FOR_GAS:.3f})")
                    return
            else:
                cs._log_trade_skipped(f"POL low (have {pol_now:.4f}, need {cs.MIN_POL_FOR_GAS:.4f})")
                print(
                    f"{runtime._nanolog()}POL low (pol≈{pol_now:.4f} < {cs.MIN_POL_FOR_GAS:.4f}) "
                    "and AUTO_TOPUP_POL=false — trade blocked"
                )
                return

        if not gas_status["ok"]:
            gas_gwei = float(gas_status.get("gas_gwei") or 0.0)
            if gas_gwei <= 400.0:
                print("⚠️ High gas but forcing trade (urgent mode)")
            else:
                cs._log_trade_skipped(
                    f"protection (gas high: {gas_status['gas_gwei']:.2f} gwei > {gas_status['max_gwei']:.2f})"
                )
                print(
                    "⛔ Gas protection active "
                    f"(gas {gas_status['gas_gwei']:.2f}/{gas_status['max_gwei']:.2f} gwei, "
                    f"POL {gas_status['pol_balance']:.4f}/{gas_status['min_pol_balance']:.4f})"
                )
                return

        if decision.direction == "USDT_TO_WMATIC":
            record_buy(current_price, decision.trade_size, "pending")

        x_signal_exec = _resolve_x_signal_enhanced_fallback_execution(
            decision,
            decision_notional_usd=decision_notional_usd,
        )
        fallback_slip_bps: int | None = None
        fallback_slip_retry_bps: int | None = None
        fallback_min_out_extra_bps: int | None = None
        if x_signal_exec is not None:
            fallback_slip_bps, fallback_slip_retry_bps, fallback_min_out_extra_bps = x_signal_exec
            if fallback_min_out_extra_bps is not None:
                print(
                    "[nanoclaw-av] X-SIGNAL enhanced execution active (48h sprint) | gated BUY "
                    f"| notional=${decision_notional_usd:.2f} "
                    f"| fallback_slip={fallback_slip_bps}/{fallback_slip_retry_bps} bps "
                    f"| min_out_extra={fallback_min_out_extra_bps} bps"
                )
            else:
                print(
                    "[nanoclaw-av] X-SIGNAL enhanced execution active (48h sprint) | small high-conviction "
                    f"| notional=${decision_notional_usd:.2f} "
                    f"| fallback_slip={fallback_slip_bps}/{fallback_slip_retry_bps} bps"
                )

        tx_hash = await approve_and_swap(
            w3,
            None,
            decision.amount_in,
            direction=decision.direction,
            token_in=decision.token_in,
            token_out=decision.token_out,
            fallback_slippage_bps=fallback_slip_bps,
            fallback_retry_slippage_bps=fallback_slip_retry_bps,
            fallback_min_out_extra_bps=fallback_min_out_extra_bps,
        )
        if tx_hash:
            attribution.notify_swap_success(decision=decision, tx_hash=tx_hash)
            if decision.direction == "USDC_TO_WMATIC" and decision.cooldown_wallet and decision.cooldown_wallet[0]:
                wallet_performance.record_copy_entry(
                    str(decision.cooldown_wallet[0]).strip(),
                    entry_price_usd=float(current_price),
                    notional_usd=float(decision.trade_size or 0.0),
                )
            elif decision.direction in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
                closed = wallet_performance.record_copy_exit(
                    exit_price_usd=float(current_price),
                    exit_notional_usd=float(_decision_notional_usd(decision, current_price_usd=current_price) or 0.0),
                )
                for row in closed:
                    print(
                        "[nanoclaw] COPY WALLET PERFORMANCE UPDATE | "
                        f"wallet={str(row.get('wallet', ''))[:10]}... "
                        f"pnl=${float(row.get('pnl_usd', 0.0)):.2f} "
                        f"notional=${float(row.get('notional_usd', 0.0)):.2f}"
                    )
            print("✅ Swap executed successfully!")
            if str(decision.direction or "").strip().upper() in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
                _profit_take_record_exit(state)
            if decision.cooldown_asset:
                sym_ca, secs_a = decision.cooldown_asset
                cs.mark_asset_traded(sym_ca, cooldown_seconds=int(secs_a))
            if decision.cooldown_wallet and decision.cooldown_wallet[0]:
                wal_cw, secs_w = decision.cooldown_wallet
                cs.mark_wallet_traded(str(wal_cw).strip(), cooldown_seconds=int(secs_w))
        else:
            print(f"{runtime._nanolog()}Swap failed — per-asset/per-wallet cooldown not applied")

        state["last_run"] = time.time()
        cs.save_state(state)
        print(f"✅ Cycle done — next in ~{cs.COOLDOWN_MINUTES} min")
    finally:
        cs.release_lock()


