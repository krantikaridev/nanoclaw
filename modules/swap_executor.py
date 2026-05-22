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
    _x_signal_min_effective_trade_usd,
)
from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from swap_executor import approve_and_swap

from external_layer.control import CycleControlSnapshot, load_cycle_control

from modules import attribution
from modules import decision_log
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
_MIN_NET_EDGE_PCT = 1.8
_MIN_NET_EDGE_ENTRY_DIRECTIONS = frozenset({"USDC_TO_EQUITY", "USDT_TO_WMATIC"})
_EST_SWAP_GAS_UNITS = 180_000.0
# Planning estimate for early decision gates (no RPC); ``main()`` uses live ``get_gas_status()`` gas.
_NET_EDGE_PLANNING_GAS_GWEI = 80.0
_MIN_NET_EDGE_POLICY_LOGGED = False


def _min_net_edge_floor_pct() -> float:
    """Runtime floor: env ``MIN_NET_EDGE_PCT`` overrides module default ``_MIN_NET_EDGE_PCT``."""
    return float(getattr(cfg, "MIN_NET_EDGE_PCT", _MIN_NET_EDGE_PCT))


def _planning_gas_gwei_for_net_edge() -> float:
    """Conservative gwei for ``determine_trade_decision`` net-edge gates (avoids per-branch RPC)."""
    return float(getattr(cfg, "NET_EDGE_PLANNING_GAS_GWEI", _NET_EDGE_PLANNING_GAS_GWEI))


def _estimate_swap_gas_cost_usd(gas_gwei: float) -> float:
    """Rough Polygon ERC-20 swap gas cost in USD (matches signal_equity_trader estimate)."""
    pol_price_usd = max(0.0, float(getattr(cfg, "POL_USD_PRICE", 0.0)))
    return max(0.0, (float(gas_gwei) * _EST_SWAP_GAS_UNITS / 1_000_000_000.0) * pol_price_usd)


def _infer_expected_gross_edge_pct(decision: TradeDecision) -> float:
    """Conservative gross upside % before gas — v1 heuristic, not a live quote."""
    direction = str(decision.direction or "").strip().upper()
    if direction == "USDC_TO_EQUITY":
        strong_tp = float(getattr(cfg, "X_SIGNAL_EQUITY_STRONG_TP_PCT", 12.0))
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
    floor = _min_net_edge_floor_pct() if min_net_edge_pct is None else float(min_net_edge_pct)
    return expected_net + 1e-9 >= floor, expected_net


def _log_min_net_edge_policy_once(*, stage: str = "planning") -> None:
    """Emit active net-edge floor once per process so ops can confirm the filter is armed."""
    global _MIN_NET_EDGE_POLICY_LOGGED
    if _MIN_NET_EDGE_POLICY_LOGGED:
        return
    _MIN_NET_EDGE_POLICY_LOGGED = True
    floor = _min_net_edge_floor_pct()
    planning_gwei = _planning_gas_gwei_for_net_edge()
    dirs = ",".join(sorted(_MIN_NET_EDGE_ENTRY_DIRECTIONS))
    print(
        f"{runtime._nanolog()}MIN_NET_EDGE_ACTIVE | floor={floor:.2f}% "
        f"| planning_gas={planning_gwei:.0f}gwei | directions={dirs} | stage={stage}"
    )


def _reject_if_low_expected_net_edge(
    decision: TradeDecision,
    *,
    trade_usd: float | None,
    gas_gwei: float,
    log_skip: Callable[[str], None],
    stage: str = "planning",
) -> bool:
    """Log and return True when the entry should be blocked for low expected net edge."""
    direction = str(decision.direction or "").strip().upper()
    if direction not in _MIN_NET_EDGE_ENTRY_DIRECTIONS:
        return False
    min_floor = _min_net_edge_floor_pct()
    notional = float(trade_usd) if trade_usd is not None else 0.0
    if notional <= 0.0:
        reason = "below_min_net_edge (missing_notional)"
        log_skip(f"low_expected_edge ({reason}; floor={min_floor:.2f}%)")
        print(
            f"[nanoclaw] Low edge rejected | direction={direction} | notional=n/a "
            f"| reason={reason} | floor={min_floor:.2f}% | stage={stage}"
        )
        return True
    passes, expected_net = trade_passes_min_net_edge(
        decision,
        trade_usd=notional,
        gas_gwei=float(gas_gwei),
    )
    if passes:
        return False
    gross_pct = _infer_expected_gross_edge_pct(decision)
    gas_usd = _estimate_swap_gas_cost_usd(float(gas_gwei))
    reason = f"below_min_net_edge (floor={min_floor:.2f}%)"
    log_skip(
        f"low_expected_edge (expected_net={expected_net:.2f}% < {min_floor:.2f}% "
        f"after gas; gross≈{gross_pct:.2f}% notional=${notional:.2f})"
    )
    print(
        f"[nanoclaw] Low edge rejected | direction={direction} | notional=${notional:.2f} "
        f"| expected_gross={gross_pct:.2f}% | gas_est=${gas_usd:.4f} "
        f"| expected_net={expected_net:.2f}% | floor={min_floor:.2f}% | reason={reason} | stage={stage}"
    )
    return True


def _decision_blocked_by_min_net_edge(
    decision: TradeDecision,
    *,
    trade_usd: float | None,
    gas_gwei: float,
    log_skip: Callable[[str], None],
) -> bool:
    """Early decision-flow gate for X-Signal / main entry directions (same rules as execution)."""
    return _reject_if_low_expected_net_edge(
        decision,
        trade_usd=trade_usd,
        gas_gwei=gas_gwei,
        log_skip=log_skip,
    )


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


def cs_evaluate_take_profit(
    current_price: float,
    state: dict,
    *,
    wmatic_balance: float | None = None,
):
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.evaluate_take_profit(
        current_price,
        state,
        wmatic_balance=wmatic_balance,
    )


def cs_try_x_signal_equity_decision(
    balances: Balances,
    *,
    dry_run: bool = False,
    state: dict | None = None,
):
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.try_x_signal_equity_decision(balances, dry_run=dry_run, state=state)


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
    *,
    state: dict | None = None,
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
        decision_log.log_main_strategy_decision(
            action="REJECT",
            reason="rotation_priority_defer_buy",
            direction="USDT_TO_WMATIC",
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=wmatic_value_usd,
            state=state,
        )
        return TradeDecision(
            message="ℹ️ Main WMATIC buy deferred (strong X-Signal BUY — Signal-Driven Rotation)"
        )

    if balances.usdt < MAIN_STRATEGY_MIN_USDT_RESERVE:
        notional = wmatic_value_usd * MAIN_STRATEGY_RESERVE_SELL_FRACTION
        decision_log.log_main_strategy_decision(
            action="TAKE",
            reason="usdt_reserve_protection",
            direction="WMATIC_TO_USDT",
            notional_usd=notional,
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=wmatic_value_usd,
            state=state,
        )
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_RESERVE_SELL_FRACTION * 1e18),
            message=(
                f"🔄 USDT RESERVE PROTECTION: ${balances.usdt:.2f} < $"
                f"{MAIN_STRATEGY_MIN_USDT_RESERVE:.0f}"
            ),
        )

    if wmatic_value_usd > MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD:
        notional = wmatic_value_usd * MAIN_STRATEGY_RESERVE_SELL_FRACTION
        decision_log.log_main_strategy_decision(
            action="TAKE",
            reason="wmatic_high_take_profit",
            direction="WMATIC_TO_USDT",
            notional_usd=notional,
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=wmatic_value_usd,
            state=state,
        )
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_RESERVE_SELL_FRACTION * 1e18),
            message=f"🔄 Taking profit (WMATIC high: ${wmatic_value_usd:.2f})",
        )

    if wmatic_value_usd < MAIN_STRATEGY_CUT_LOSS_WMATIC_USD and balances.wmatic > MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE:
        notional = wmatic_value_usd * MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION
        decision_log.log_main_strategy_decision(
            action="TAKE",
            reason="wmatic_low_cut_loss",
            direction="WMATIC_TO_USDT",
            notional_usd=notional,
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=wmatic_value_usd,
            state=state,
        )
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION * 1e18),
            message=f"🔄 Cutting loss (WMATIC down: ${wmatic_value_usd:.2f})",
        )

    # Signal-Driven Rotation (May 2026): prefer small WMATIC→stable rotation over USDT→WMATIC
    # accumulation when the stack is below the high take-profit band — reduces over-reliance on
    # large WMATIC balances for main-strategy participation (P2/force paths handle dust/min guards).
    idle_rotation = _main_strategy_idle_rotation_sell_decision(
        balances,
        current_price,
        state=state,
    )
    if idle_rotation is not None:
        return idle_rotation

    decision_log.log_main_strategy_decision(
        action="ACCEPT",
        reason="usdt_to_wmatic_accumulate",
        direction="USDT_TO_WMATIC",
        notional_usd=float(trade_size),
        wmatic_balance=float(balances.wmatic),
        wmatic_usd=wmatic_value_usd,
        state=state,
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
    "[nanoclaw] FORCE small profit take | WMATIC=${wm:.2f} {stack_label}, "
    "no exit for {cycles} cycles | notional=${notional:.2f} | bypassing min_notional"
)

# Signal-Driven Rotation (May 2026): reduce WMATIC dependency — relax P2/force when stack is below $7.
_MAIN_STRATEGY_LOW_WMATIC_USD_THRESHOLD = 7.0
_MAIN_STRATEGY_LOW_WMATIC_P2_WM_MIN_USD = 2.0
_MAIN_STRATEGY_LOW_WMATIC_P2_SIGNAL_MIN = 0.45
_MAIN_STRATEGY_LOW_WMATIC_FORCE_WM_MIN_USD = 2.0
_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN = 3

# Signal-Driven Rotation (May 2026): after idle WMATIC→stable cycles, rotate a small stable slice via X-SIGNAL.
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_CYCLES_MIN = 6
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_MIN_STABLE_USD = 50.0
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_MIN_SIGNAL = 0.75
# Relaxed fallback when WMATIC stack is low — still rotates stables without waiting for a large WMATIC exit.
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_CYCLES_MIN = 4
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_STABLE_USD = 35.0
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_SIGNAL = 0.65
_MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_LOW = 0.32
_MAIN_STRATEGY_IDLE_ROTATION_NOTIONAL_FLOOR_LOW = 1.5
_MAIN_STRATEGY_STATUS_LOG = "[nanoclaw] MAIN_STRATEGY_STATUS"
_MAIN_STRATEGY_OUTCOME_LOG = "[nanoclaw] MAIN_STRATEGY_OUTCOME"
_STABLE_ROTATION_FALLBACK_LOG = (
    "[nanoclaw] Signal-Driven Rotation: stable fallback | cycles_idle={cycles} | "
    "stables=${stable:.2f} | X-SIGNAL BUY eligible"
)

# Signal-driven execution quality (May 2026): small high-conviction X-SIGNAL (~$11) — fallback slippage + min_out.
_X_SIGNAL_SMALL_HIGH_CONVICTION_MAX_NOTIONAL_USD = 12.0
_X_SIGNAL_STF_STATE_KEY = "x_signal_stf_backoff"
_X_SIGNAL_STF_LOG = "[nanoclaw] X-SIGNAL execution quality"


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
    """TEMPORARY SPRINT FIX - May 2026: HOLD snapshots must not zero relief when stack is healthy.

    Signal-Driven Rotation (May 2026): when stack is low (< $7), ignore HOLD for scoring so small
    WMATIC→stable relief can still rotate capital.
    """
    if profit_signal is None:
        return None
    reason = str(profit_signal.get("reason") or "").strip().upper()
    if reason != "HOLD":
        return profit_signal
    if wmatic_usd_equiv is not None and _profit_take_wmatic_stack_low(float(wmatic_usd_equiv)):
        return None
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
    # Signal-Driven Rotation (May 2026): lenient floors when stack is healthy (≥ $7) or low-but-actionable.
    if wmatic_usd_equiv is None:
        return strength
    wm = float(wmatic_usd_equiv)
    if wm + 1e-9 < wm_min and not _profit_take_wmatic_stack_low(wm):
        return strength
    signal_floor = _profit_take_p2_signal_min(wm)
    if valid_exit_reason:
        return max(strength, signal_floor)
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
    When WMATIC stack ≥ $7 and exit reason is not HOLD, strength is never below 0.55.
    When stack < $7 (Signal-Driven Rotation), floor drops to 0.45 for small profit takes.
    """
    wm_min = float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN)
    profit_signal = _profit_signal_for_relief_scoring(
        profit_signal,
        wmatic_usd_equiv=wmatic_usd_equiv,
    )
    wm_for_floor = float(wmatic_usd_equiv) if wmatic_usd_equiv is not None else wm_min
    floor = _profit_take_p2_signal_min(wm_for_floor)

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


def _profit_take_wmatic_stack_low(wm_equiv_usd: float) -> bool:
    """Signal-Driven Rotation (May 2026): stack below $7 — use relaxed P2/force thresholds."""
    return float(wm_equiv_usd) + 1e-9 < float(_MAIN_STRATEGY_LOW_WMATIC_USD_THRESHOLD)


def _profit_take_p2_wm_stack_min_usd(wm_equiv_usd: float) -> float:
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        return float(_MAIN_STRATEGY_LOW_WMATIC_P2_WM_MIN_USD)
    return float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN)


def _profit_take_p2_signal_min(wm_equiv_usd: float) -> float:
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        return float(_MAIN_STRATEGY_LOW_WMATIC_P2_SIGNAL_MIN)
    return float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH)


def _profit_take_force_wm_min_usd(wm_equiv_usd: float) -> float:
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        return float(_MAIN_STRATEGY_LOW_WMATIC_FORCE_WM_MIN_USD)
    return float(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN)


def _profit_take_force_cycles_min(wm_equiv_usd: float) -> int:
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        return int(_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN)
    return int(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN)


def _main_strategy_stable_rotation_fallback_params(
    wm_equiv_usd: float,
) -> tuple[int, float, float]:
    """Return (cycles_min, min_stables_usd, min_signal) for stable→equity fallback."""
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        return (
            int(_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_CYCLES_MIN),
            float(_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_STABLE_USD),
            float(_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_SIGNAL),
        )
    return (
        int(_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_CYCLES_MIN),
        float(_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_MIN_STABLE_USD),
        float(_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_MIN_SIGNAL),
    )


def _main_strategy_idle_rotation_sell_fraction(wm_equiv_usd: float) -> float:
    """Smaller sell slice when WMATIC stack is depleted — keeps rotation gas-efficient."""
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        # ~32% on a ~$5.7 stack clears the $1.50 low-stack notional floor for idle rotation.
        return float(_MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_LOW)
    return float(MAIN_STRATEGY_RESERVE_SELL_FRACTION)


def _main_strategy_idle_rotation_eligibility(
    balances: Balances,
    current_price: float,
    state: dict | None,
) -> tuple[bool, str]:
    """Whether main strategy would emit an idle WMATIC→stable rotation sell this cycle."""
    wm_equiv = float(balances.wmatic) * float(current_price)
    if wm_equiv + 1e-9 >= float(MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD):
        return False, "wmatic_above_tp_band"
    if wm_equiv + 1e-9 < _profit_take_force_wm_min_usd(wm_equiv):
        return False, "wmatic_below_force_floor"
    cycles = _profit_take_cycles_since_exit(state)
    cycles_min = _profit_take_force_cycles_min(wm_equiv)
    if cycles < cycles_min:
        return False, f"idle_cycles={cycles}/{cycles_min}"
    fraction = _main_strategy_idle_rotation_sell_fraction(wm_equiv)
    notional = wm_equiv * fraction
    floor = (
        float(_MAIN_STRATEGY_IDLE_ROTATION_NOTIONAL_FLOOR_LOW)
        if _profit_take_wmatic_stack_low(wm_equiv)
        else float(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD)
    )
    if notional + 1e-9 < floor:
        return False, f"notional_${notional:.2f}_below_${floor:.2f}"
    if int(balances.wmatic * fraction * 1e18) <= 0:
        return False, "zero_amount_in"
    return True, "eligible"


def _main_strategy_idle_rotation_sell_decision(
    balances: Balances,
    current_price: float,
    *,
    state: dict | None = None,
) -> TradeDecision | None:
    """Small WMATIC→stable exit after idle cycles — capital rotation without high WMATIC stack."""
    eligible, note = _main_strategy_idle_rotation_eligibility(balances, current_price, state)
    if not eligible:
        return None
    wm_equiv = float(balances.wmatic) * float(current_price)
    fraction = _main_strategy_idle_rotation_sell_fraction(wm_equiv)
    notional = wm_equiv * fraction
    low = _profit_take_wmatic_stack_low(wm_equiv)
    reason = "low_wmatic_idle_rotation" if low else "moderate_wmatic_idle_rotation"
    cycles = _profit_take_cycles_since_exit(state)
    print(
        f"{runtime._nanolog()}Main strategy idle rotation | wmatic_usd=${wm_equiv:.2f} | "
        f"low_stack={low} | cycles_since_exit={cycles} | sell_fraction={fraction:.2f} | "
        f"notional≈${notional:.2f} | note={note}"
    )
    decision_log.log_main_strategy_decision(
        action="TAKE",
        reason=reason,
        direction="WMATIC_TO_USDT",
        notional_usd=notional,
        wmatic_balance=float(balances.wmatic),
        wmatic_usd=wm_equiv,
        extra=f"cycles_since_exit={cycles}",
        state=state,
    )
    return TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(balances.wmatic * fraction * 1e18),
        message=(
            f"🔄 Idle WMATIC rotation ({'low' if low else 'moderate'} stack: "
            f"${wm_equiv:.2f}, {cycles} cycles since exit)"
        ),
    )


def _log_main_strategy_cycle_status(
    balances: Balances,
    current_price: float,
    profit_signal: dict | None,
    state: dict | None,
) -> None:
    """Signal-Driven Rotation (May 2026): per-cycle visibility into main-strategy activity vs quiet."""
    wm_usd = float(balances.wmatic) * float(current_price)
    low = _profit_take_wmatic_stack_low(wm_usd)
    cycles = _profit_take_cycles_since_exit(state)
    stable = float(balances.usdt) + float(balances.usdc)
    pt_reason = str((profit_signal or {}).get("reason") or "n/a").strip().upper()
    fb_cycles, fb_stable_min, fb_signal_min = _main_strategy_stable_rotation_fallback_params(wm_usd)
    fallback_ready = cycles >= fb_cycles and stable + 1e-9 >= fb_stable_min
    idle_eligible, idle_note = _main_strategy_idle_rotation_eligibility(
        balances,
        current_price,
        state,
    )
    activity = "active_idle_rotation" if idle_eligible else (
        "active_p2_or_force" if low or cycles >= _profit_take_force_cycles_min(wm_usd) else "quiet_accumulate_or_wait"
    )
    print(
        f"{_MAIN_STRATEGY_STATUS_LOG} | wmatic_usd=${wm_usd:.2f} | low_wmatic_stack={low} | "
        f"cycles_since_wm_exit={cycles} | stables=${stable:.2f} | profit_take_reason={pt_reason} | "
        f"activity={activity} | idle_rotation_eligible={idle_eligible} | idle_rotation_note={idle_note} | "
        f"p2_wm_min=${_profit_take_p2_wm_stack_min_usd(wm_usd):.2f} | "
        f"p2_signal_min={_profit_take_p2_signal_min(wm_usd):.2f} | "
        f"force_wm_min=${_profit_take_force_wm_min_usd(wm_usd):.2f} | "
        f"force_cycles_min={_profit_take_force_cycles_min(wm_usd)} | "
        f"stable_fallback_ready={fallback_ready} | stable_fallback_min_signal={fb_signal_min:.2f}"
    )


def _log_main_strategy_outcome(decision: TradeDecision) -> None:
    direction = str(decision.direction or "").strip().upper() or "NONE"
    actionable = bool(decision.should_execute)
    msg = str(decision.message or "").strip()
    quiet = (not actionable) or (
        direction == "NONE" and bool(msg) and ("deferred" in msg.lower() or msg.startswith("ℹ️"))
    )
    if actionable and direction == "USDT_TO_WMATIC":
        quiet_reason = "accumulate_wmatic"
    elif actionable and direction in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        quiet_reason = "wmatic_to_stable_exit"
    elif quiet:
        quiet_reason = "deferred_or_info"
    else:
        quiet_reason = "no_trade"
    note = msg[:100] if msg else "no_message"
    print(
        f"{_MAIN_STRATEGY_OUTCOME_LOG} | direction={direction} | actionable={actionable} | "
        f"quiet={quiet} | quiet_reason={quiet_reason} | note={note}"
    )


def _main_strategy_stable_rotation_fallback(
    balances: Balances,
    current_price: float,
    *,
    dry_run: bool = False,
    state: dict | None = None,
) -> Optional[TradeDecision]:
    """Signal-Driven Rotation (May 2026): idle WMATIC profit-take → small stable→equity via X-SIGNAL.

    When WMATIC stack is low, uses relaxed cycles/stables/signal floors so capital can still rotate
    without waiting for a large WMATIC→stable exit (reduces over-reliance on high WMATIC balance).
    """
    cs = _facade()
    if not bool(getattr(cs, "ENABLE_X_SIGNAL_EQUITY", False)):
        return None
    wm_equiv = float(balances.wmatic) * float(current_price)
    cycles = _profit_take_cycles_since_exit(state)
    stable = float(balances.usdt) + float(balances.usdc)
    fb_cycles_min, fb_stable_min, fb_signal_min = _main_strategy_stable_rotation_fallback_params(wm_equiv)
    if cycles < fb_cycles_min:
        return None
    if stable + 1e-9 < fb_stable_min:
        print(
            f"{runtime._nanolog()}Signal-Driven Rotation: stable fallback skipped — "
            f"stables=${stable:.2f} < ${fb_stable_min:.0f} (low_wmatic={_profit_take_wmatic_stack_low(wm_equiv)})"
        )
        return None
    xd = cs_try_x_signal_equity_decision(balances, dry_run=dry_run)
    if not xd or not xd.should_execute:
        print(
            f"{runtime._nanolog()}Signal-Driven Rotation: stable fallback skipped — "
            f"no executable X-SIGNAL plan after {cycles} idle cycles"
        )
        return None
    direction = str(xd.direction or "").strip().upper()
    if direction != "USDC_TO_EQUITY":
        return None
    strength = xd.signal_strength
    if strength is None or float(strength) + 1e-9 < fb_signal_min:
        print(
            f"{runtime._nanolog()}Signal-Driven Rotation: stable fallback skipped — "
            f"signal={strength} below {fb_signal_min:.2f} (low_wmatic_stack)"
        )
        return None
    print(_STABLE_ROTATION_FALLBACK_LOG.format(cycles=cycles, stable=stable))
    return xd


def _profit_take_force_small_relief_eligible(
    *,
    direction: str,
    wm_equiv_usd: float,
    notional_usd: float,
    cycles_since_exit: int,
) -> bool:
    """TEMPORARY SPRINT FIX - May 2026: force small profit take when stack + idle cycles qualify.

    Signal-Driven Rotation (May 2026): when WMATIC stack < $7, force threshold drops to $2 and 3 cycles.
    """
    dir_u = str(direction or "").strip().upper()
    if dir_u not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    force_wm_min = _profit_take_force_wm_min_usd(wm_equiv_usd)
    floor_usd = float(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD)
    cycles_min = _profit_take_force_cycles_min(wm_equiv_usd)
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
        stack_label = "low_stack" if _profit_take_wmatic_stack_low(wm_equiv_usd) else "healthy_stack"
        print(
            _PROFIT_TAKE_FORCE_SMALL_LOG.format(
                wm=wm_equiv_usd,
                stack_label=stack_label,
                cycles=cycles_since_exit,
                notional=float(notional_usd),
            )
        )
        allowed = True
        reason = "force_no_exit_cycles"
    elif notional_usd + 1e-9 < floor_usd:
        allowed = False
        reason = "notional_below_floor"
    elif wm_equiv_usd + 1e-9 < _profit_take_p2_wm_stack_min_usd(wm_equiv_usd):
        allowed = False
        reason = "wmatic_stack_below_min"
    elif abs(float(strength)) + 1e-9 < _profit_take_p2_signal_min(wm_equiv_usd):
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
_X_SIGNAL_VERY_STRONG_STRENGTH = 0.90


def _x_signal_min_out_extra_bps(signal_strength: float | None) -> int:
    """Stack base min_out buffer with optional high-conviction add-on."""
    extra = 0
    if signal_strength is not None and abs(float(signal_strength)) + 1e-9 >= _X_SIGNAL_VERY_STRONG_STRENGTH:
        extra = int(cfg.X_SIGNAL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS)
    return extra


def _is_x_signal_usdc_equity_buy(decision: TradeDecision | None) -> bool:
    return (
        decision is not None
        and bool(decision.should_execute)
        and str(decision.direction or "").strip().upper() == "USDC_TO_EQUITY"
    )


def _x_signal_symbol_from_decision(decision: TradeDecision) -> str:
    asset = getattr(decision, "cooldown_asset", None)
    if isinstance(asset, tuple) and len(asset) >= 1:
        sym = str(asset[0] or "").strip().upper()
        if sym:
            return sym
    return "UNKNOWN"


def _x_signal_stf_pause_entry(state: dict | None, symbol: str) -> dict:
    if state is None:
        raise ValueError("state is required for X-SIGNAL STF backoff tracking")
    root = state.setdefault(_X_SIGNAL_STF_STATE_KEY, {})
    return root.setdefault(str(symbol).strip().upper(), {"failures": 0, "paused_until": 0.0})


def _x_signal_stf_pause_active(state: dict | None, symbol: str) -> tuple[bool, str]:
    """True when repeated STF failures triggered a temporary pause for this asset."""
    if not state or not symbol:
        return False, ""
    entry = _x_signal_stf_pause_entry(state, symbol)
    until = float(entry.get("paused_until") or 0.0)
    now = time.time()
    if until > now:
        remain = int(until - now)
        return True, f"stf_pause_active ({remain}s remaining, failures={int(entry.get('failures') or 0)})"
    if until > 0 and until <= now:
        entry["paused_until"] = 0.0
    return False, ""


def _record_x_signal_stf_failure(state: dict, decision: TradeDecision, swap_outcome: dict | None) -> None:
    """Signal-driven execution quality (May 2026): backoff asset after repeated STF reverts."""
    if not swap_outcome or not bool(swap_outcome.get("stf")):
        return
    sym = _x_signal_symbol_from_decision(decision)
    entry = _x_signal_stf_pause_entry(state, sym)
    entry["failures"] = int(entry.get("failures") or 0) + 1
    threshold = max(1, int(cfg.X_SIGNAL_STF_PAUSE_AFTER_FAILURES))
    pause_secs = max(60, int(cfg.X_SIGNAL_STF_PAUSE_SECONDS))
    print(
        f"{_X_SIGNAL_STF_LOG} | STF failure recorded | sym={sym} | "
        f"failures={entry['failures']}/{threshold} | revert={str(swap_outcome.get('revert_reason') or '')[:120]}"
    )
    if int(entry["failures"]) >= threshold:
        entry["paused_until"] = time.time() + float(pause_secs)
        entry["failures"] = 0
        print(
            f"{_X_SIGNAL_STF_LOG} | pausing X-SIGNAL BUY for {sym} | "
            f"duration={pause_secs}s | reason=repeated_stf"
        )


def _clear_x_signal_stf_pause(state: dict, decision: TradeDecision) -> None:
    sym = _x_signal_symbol_from_decision(decision)
    root = state.get(_X_SIGNAL_STF_STATE_KEY) or {}
    if sym in root:
        root.pop(sym, None)
        print(f"{_X_SIGNAL_STF_LOG} | STF backoff cleared after successful swap | sym={sym}")


def _x_signal_apply_stf_pause_filter(
    decision: TradeDecision | None,
    *,
    state: dict | None,
) -> TradeDecision | None:
    if not _is_x_signal_usdc_equity_buy(decision) or state is None:
        return decision
    sym = _x_signal_symbol_from_decision(decision)
    paused, detail = _x_signal_stf_pause_active(state, sym)
    if not paused:
        return decision
    print(f"{_X_SIGNAL_STF_LOG} | skipping BUY | sym={sym} | {detail}")
    decision_log.log_x_signal_decision(
        sym,
        "REJECT",
        "stf_pause",
        signal=decision.signal_strength,
        notional_usd=None,
        extra=detail,
        state=state,
    )
    return None


def _x_signal_small_high_conviction_relaxed_slippage(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> tuple[int, int] | None:
    """Signal-driven execution quality (May 2026): high fallback slippage for small USDC→equity X-SIGNAL (>=0.85)."""
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
    """TEMPORARY (48-hour sprint): USDC→equity BUY that passed the dynamic effective gate at plan build."""
    if str(decision.direction or "").strip().upper() != "USDC_TO_EQUITY":
        return False
    if bool(getattr(decision, "x_signal_gated_execution", False)):
        return True
    if decision_notional_usd is None:
        return False
    strength = decision.signal_strength
    if strength is not None:
        min_gate = float(_x_signal_min_effective_trade_usd(float(strength)))
    else:
        min_gate = float(_X_SIGNAL_MIN_EFFECTIVE_TRADE_USD)
    return float(decision_notional_usd) + 1e-9 >= min_gate


def _x_signal_gated_trade_relaxed_slippage(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> tuple[int, int] | None:
    """Signal-driven execution quality (May 2026): high fallback slippage for gated X-SIGNAL USDC→equity BUYs."""
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
    """Signal-driven execution quality (May 2026): (primary_bps, retry_bps, min_out_extra_bps) for fallback router."""
    strength = decision.signal_strength
    small = _x_signal_small_high_conviction_relaxed_slippage(
        decision,
        decision_notional_usd=decision_notional_usd,
    )
    if small is not None:
        min_out = int(cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS) + _x_signal_min_out_extra_bps(
            strength
        )
        return small[0], small[1], min_out
    gated = _x_signal_gated_trade_relaxed_slippage(
        decision,
        decision_notional_usd=decision_notional_usd,
    )
    if gated is not None:
        min_out = int(cfg.X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS) + _x_signal_min_out_extra_bps(strength)
        return gated[0], gated[1], min_out
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
    _log_min_net_edge_policy_once(stage="planning")
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

    should_take_profit, profit_signal = cs_evaluate_take_profit(
        current_price,
        state,
        wmatic_balance=float(balances.wmatic),
    )
    planning_gas_gwei = _planning_gas_gwei_for_net_edge()

    def _resolve_x_signal_equity_decision() -> Optional[TradeDecision]:
        if not cs.ENABLE_X_SIGNAL_EQUITY:
            return None
        xd_local = cs_try_x_signal_equity_decision(balances, dry_run=dry_run, state=state)
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
            xd_local = _x_signal_apply_stf_pause_filter(xd_local, state=state)
        if xd_local and xd_local.should_execute:
            print("🔍 DECISION PATH: X_SIGNAL_EQUITY")
            x_dust_min = _x_signal_equity_effective_dust_min(balances)
            x_notional = _decision_notional_usd(xd_local, current_price_usd=current_price)
            _, edge_x = trade_passes_min_net_edge(
                xd_local,
                trade_usd=float(x_notional or 0.0),
                gas_gwei=planning_gas_gwei,
            )
            if _decision_blocked_by_min_net_edge(
                xd_local,
                trade_usd=x_notional,
                gas_gwei=planning_gas_gwei,
                log_skip=cs._log_trade_skipped,
            ):
                decision_log.log_x_signal_decision(
                    "n/a",
                    "REJECT",
                    "below_min_net_edge",
                    signal=xd_local.signal_strength,
                    expected_edge_pct=edge_x,
                    notional_usd=x_notional,
                    wmatic_balance=float(balances.wmatic),
                    extra=f"floor={_min_net_edge_floor_pct():.2f}%",
                    state=state,
                )
            elif _defer_if_dust(
                xd_local,
                branch_name="X_SIGNAL_EQUITY",
                current_price_usd=current_price,
                min_trade_usd=x_dust_min,
            ):
                decision_log.log_x_signal_decision(
                    "n/a",
                    "REJECT",
                    "dust_deferred",
                    wmatic_balance=float(balances.wmatic),
                    notional_usd=x_notional,
                    expected_edge_pct=edge_x,
                    extra="branch=X_SIGNAL_EQUITY",
                    state=state,
                )
            else:
                _cooldown_asset = getattr(xd_local, "cooldown_asset", None)
                if isinstance(_cooldown_asset, tuple) and len(_cooldown_asset) >= 1:
                    sym_x = str(_cooldown_asset[0] or "n/a")
                else:
                    sym_x = "n/a"
                decision_log.record_x_signal_cycle_outcome(
                    state,
                    taken=True,
                    reason="executable_plan",
                    wmatic_balance=float(balances.wmatic),
                )
                decision_log.log_x_signal_decision(
                    sym_x,
                    "ACCEPT",
                    "cycle_selected",
                    signal=xd_local.signal_strength,
                    expected_edge_pct=edge_x,
                    notional_usd=x_notional,
                    wmatic_balance=float(balances.wmatic),
                    extra=f"direction={xd_local.direction}",
                    state=state,
                    bump_symbol_counter=False,
                )
                return xd_local
        cycle_reason = "no_plan" if xd_local is None else "not_executable"
        if xd_local is not None and (pause_active or entries_paused):
            cycle_reason = "paused_or_defensive"
        decision_log.record_x_signal_cycle_outcome(
            state,
            taken=False,
            reason=cycle_reason,
            wmatic_balance=float(balances.wmatic),
        )
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
        pt_notional = _decision_notional_usd(profit_decision, current_price_usd=current_price)
        if not _defer_if_dust(
            profit_decision,
            branch_name="PROFIT_TAKE",
            current_price_usd=current_price,
        ):
            decision_log.log_profit_take_decision(
                action="TAKE",
                reason=str(profit_signal.get("reason") or "unknown"),
                signal_strength=float(profit_signal.get("gain_pct", 0) or 0) / 100.0,
                notional_usd=pt_notional,
                wmatic_balance=float(balances.wmatic),
                extra=f"direction={profit_decision.direction}",
                state=state,
            )
            decision_log.log_tracking_summary(state)
            return profit_decision
        decision_log.log_profit_take_decision(
            action="DEFER",
            reason="dust_deferred",
            notional_usd=pt_notional,
            wmatic_balance=float(balances.wmatic),
            extra=str(profit_signal.get("reason") or ""),
            state=state,
        )

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
    _log_main_strategy_cycle_status(balances, current_price, profit_signal, state)
    # Signal-Driven Rotation (May 2026): idle WMATIC profit-take → opportunistic stable→equity via X-SIGNAL.
    if not pause_active and not entries_paused:
        fallback_xd = _main_strategy_stable_rotation_fallback(
            balances,
            current_price,
            dry_run=dry_run,
            state=state,
        )
        if fallback_xd is not None:
            print(
                "🔍 DECISION PATH: MAIN_STRATEGY_STABLE_ROTATION_FALLBACK "
                "(Signal-Driven Rotation — idle WMATIC profit-take)"
            )
            x_dust_min_fb = _x_signal_equity_effective_dust_min(balances)
            fb_notional = _decision_notional_usd(fallback_xd, current_price_usd=current_price)
            if _decision_blocked_by_min_net_edge(
                fallback_xd,
                trade_usd=fb_notional,
                gas_gwei=planning_gas_gwei,
                log_skip=cs._log_trade_skipped,
            ):
                decision_log.log_main_strategy_decision(
                    action="REJECT",
                    reason="below_min_net_edge",
                    wmatic_balance=float(balances.wmatic),
                    wmatic_usd=float(balances.wmatic) * float(current_price),
                    extra=f"stable_rotation_fallback notional=${fb_notional}",
                    state=state,
                )
            elif not _defer_if_dust(
                fallback_xd,
                branch_name="MAIN_STABLE_ROTATION_FALLBACK",
                current_price_usd=current_price,
                min_trade_usd=x_dust_min_fb,
            ):
                _log_main_strategy_outcome(fallback_xd)
                return fallback_xd
    main_decision = select_main_strategy_trade(balances, current_price, state=state)
    _log_main_strategy_outcome(main_decision)
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
    if main_decision.should_execute and main_dir == "USDT_TO_WMATIC":
        main_notional = _decision_notional_usd(main_decision, current_price_usd=current_price)
        if _decision_blocked_by_min_net_edge(
            main_decision,
            trade_usd=main_notional,
            gas_gwei=planning_gas_gwei,
            log_skip=cs._log_trade_skipped,
        ):
            low_edge = TradeDecision(
                message=(
                    f"ℹ️ Main strategy skipped (expected net edge below {_min_net_edge_floor_pct():.2f}% "
                    "after gas)"
                ),
            )
            _log_main_strategy_outcome(low_edge)
            decision_log.log_main_strategy_decision(
                action="REJECT",
                reason="below_min_net_edge",
                wmatic_balance=float(balances.wmatic),
                wmatic_usd=float(balances.wmatic) * float(current_price),
                extra=f"notional=${main_notional}",
                state=state,
            )
            decision_log.log_tracking_summary(state)
            return low_edge
    if _defer_if_dust(
        main_decision,
        branch_name="MAIN_STRATEGY",
        current_price_usd=current_price,
    ):
        deferred = TradeDecision(message="ℹ️ Main strategy deferred (dust-sized trade)")
        _log_main_strategy_outcome(deferred)
        decision_log.log_main_strategy_decision(
            action="DEFER",
            reason="dust_deferred",
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=float(balances.wmatic) * float(current_price),
            state=state,
        )
        decision_log.log_tracking_summary(state)
        return deferred
    decision_log.log_tracking_summary(state)
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
    _log_min_net_edge_policy_once(stage="execution")
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
            stage="execution",
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
        is_x_signal_buy = _is_x_signal_usdc_equity_buy(decision)
        x_sym = _x_signal_symbol_from_decision(decision) if is_x_signal_buy else ""
        if x_signal_exec is not None:
            fallback_slip_bps, fallback_slip_retry_bps, fallback_min_out_extra_bps = x_signal_exec
            tier = "gated" if fallback_min_out_extra_bps and int(fallback_min_out_extra_bps) >= int(
                cfg.X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS
            ) else "small_high_conviction"
            print(
                f"{_X_SIGNAL_STF_LOG} | EXEC ATTEMPT | sym={x_sym} | tier={tier} | "
                f"notional=${decision_notional_usd:.2f} | signal={decision.signal_strength} | "
                f"fallback_slip={fallback_slip_bps}/{fallback_slip_retry_bps} bps | "
                f"min_out_extra={fallback_min_out_extra_bps} bps | v3_fee=best_of(500,3000,10000)"
            )
        elif is_x_signal_buy:
            print(
                f"{_X_SIGNAL_STF_LOG} | EXEC ATTEMPT | sym={x_sym} | tier=standard | "
                f"notional=${decision_notional_usd:.2f} | signal={decision.signal_strength}"
            )

        swap_outcome: dict = {}
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
            swap_outcome=swap_outcome if is_x_signal_buy else None,
        )
        if tx_hash:
            if is_x_signal_buy:
                _clear_x_signal_stf_pause(state, decision)
                print(f"{_X_SIGNAL_STF_LOG} | EXEC SUCCESS | sym={x_sym} | tx={tx_hash}")
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
                decision_log.record_profit_take_execution(state, success=True, reason="swap_ok")
                _profit_take_record_exit(state)
            if decision.cooldown_asset:
                sym_ca, secs_a = decision.cooldown_asset
                cs.mark_asset_traded(sym_ca, cooldown_seconds=int(secs_a))
            if decision.cooldown_wallet and decision.cooldown_wallet[0]:
                wal_cw, secs_w = decision.cooldown_wallet
                cs.mark_wallet_traded(str(wal_cw).strip(), cooldown_seconds=int(secs_w))
        else:
            if is_x_signal_buy:
                _record_x_signal_stf_failure(state, decision, swap_outcome)
                stf_flag = bool(swap_outcome.get("stf"))
                print(
                    f"{_X_SIGNAL_STF_LOG} | EXEC FAILED | sym={x_sym} | stf={stf_flag} | "
                    f"revert={str(swap_outcome.get('revert_reason') or 'unknown')[:160]}"
                )
            if str(decision.direction or "").strip().upper() in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
                decision_log.record_profit_take_execution(state, success=False, reason="swap_failed")
            print(f"{runtime._nanolog()}Swap failed — per-asset/per-wallet cooldown not applied")

        state["last_run"] = time.time()
        cs.save_state(state)
        print(f"✅ Cycle done — next in ~{cs.COOLDOWN_MINUTES} min")
    finally:
        cs.release_lock()


