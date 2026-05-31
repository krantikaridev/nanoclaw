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
    _x_signal_recovery_gate_relaxation_active,
)
from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from swap_executor import _x_signal_fallback_slippage_ramp, approve_and_swap

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

# Foundation quality filter — block entry trades unlikely to clear gas + fees (avoids repeated low-edge churn).
# Conservative default 2.0% net after gas; override via env ``MIN_NET_EDGE_PCT`` (see config.py / .env.example).
_MIN_NET_EDGE_PCT = 2.0
_MIN_NET_EDGE_FEE_BUFFER_PCT = 0.75
_MIN_NET_EDGE_ENTRY_DIRECTIONS = frozenset({"USDC_TO_EQUITY", "USDT_TO_WMATIC"})
_EST_SWAP_GAS_UNITS = 180_000.0
# Planning estimate for early decision gates (no RPC); ``main()`` uses live ``get_gas_status()`` gas.
_NET_EDGE_PLANNING_GAS_GWEI = 120.0
_MIN_NET_EDGE_POLICY_LOGGED = False


def _min_net_edge_floor_pct() -> float:
    """Runtime floor: env ``MIN_NET_EDGE_PCT`` overrides module default ``_MIN_NET_EDGE_PCT``."""
    return float(getattr(cfg, "MIN_NET_EDGE_PCT", _MIN_NET_EDGE_PCT))


def _planning_gas_gwei_for_net_edge() -> float:
    """Conservative gwei for ``determine_trade_decision`` net-edge gates (avoids per-branch RPC)."""
    return float(getattr(cfg, "NET_EDGE_PLANNING_GAS_GWEI", _NET_EDGE_PLANNING_GAS_GWEI))


def _min_net_edge_fee_buffer_pct() -> float:
    """Swap fee/slippage reserve subtracted from gross edge before gas (planning only)."""
    return max(0.0, float(getattr(cfg, "MIN_NET_EDGE_FEE_BUFFER_PCT", _MIN_NET_EDGE_FEE_BUFFER_PCT)))


def _estimate_swap_gas_cost_usd(gas_gwei: float) -> float:
    """Rough Polygon ERC-20 swap gas cost in USD (matches signal_equity_trader estimate)."""
    pol_price_usd = max(0.0, float(getattr(cfg, "POL_USD_PRICE", 0.0)))
    return max(0.0, (float(gas_gwei) * _EST_SWAP_GAS_UNITS / 1_000_000_000.0) * pol_price_usd)


def _x_signal_strength_scale(signal_strength: float) -> float:
    """Linear 0→1 scale from eligibility floor (0.6) to full conviction (1.0); no artificial floor."""
    s = abs(float(signal_strength))
    if s < 0.6:
        return 0.0
    return min(1.0, (s - 0.6) / 0.4)


def plan_x_signal_gross_edge_pct(
    signal_strength: float,
    upside_pct: float | None = None,
) -> float:
    """Conservative gross edge % for X-SIGNAL USDC→equity net-edge planning (not a live quote)."""
    strong_tp = float(getattr(cfg, "X_SIGNAL_EQUITY_STRONG_TP_PCT", 12.0))
    scale = _x_signal_strength_scale(signal_strength)
    # No 25%-of-TP floor — weak signals must not inherit a 3% gross cushion that clears a 2% net gate.
    heuristic = strong_tp * scale
    if upside_pct is not None and float(upside_pct) > 0:
        capped_upside = min(float(upside_pct), strong_tp * 1.25)
        realization = 0.35 + 0.45 * scale
        from_upside = capped_upside * realization
        return min(heuristic, from_upside)
    return heuristic


def plan_main_strategy_gross_edge_pct() -> float:
    """Conservative gross edge % for main USDT→WMATIC entry (below take-profit target)."""
    explicit = float(getattr(cfg, "MAIN_STRATEGY_ENTRY_EDGE_PCT", 0.0))
    if explicit > 0.0:
        return max(0.0, explicit)
    take_profit = max(0.0, float(getattr(cfg, "TAKE_PROFIT_PCT", 5.0)))
    frac = max(0.0, min(1.0, float(getattr(cfg, "MAIN_STRATEGY_ENTRY_EDGE_FRAC", 0.70))))
    return take_profit * frac


def _effective_gross_edge_after_fee_buffer(gross_edge_pct: float) -> float:
    return max(0.0, float(gross_edge_pct) - _min_net_edge_fee_buffer_pct())


def _infer_expected_gross_edge_pct(decision: TradeDecision) -> float:
    """Conservative gross upside % before fee buffer and gas — v1 heuristic, not a live quote."""
    if decision.expected_gross_edge_pct is not None:
        return max(0.0, float(decision.expected_gross_edge_pct))
    direction = str(decision.direction or "").strip().upper()
    if direction == "USDC_TO_EQUITY":
        strength = decision.signal_strength
        if strength is not None and float(strength) > 0:
            return plan_x_signal_gross_edge_pct(float(strength))
        return max(0.0, float(getattr(cfg, "X_SIGNAL_EQUITY_STRONG_TP_PCT", 12.0)) * 0.25)
    if direction == "USDT_TO_WMATIC":
        return plan_main_strategy_gross_edge_pct()
    return 0.0


def estimate_expected_net_edge_pct(
    *,
    trade_usd: float,
    expected_gross_edge_pct: float,
    gas_cost_usd: float,
    fee_buffer_pct: float | None = None,
) -> float:
    """Net expected return % of notional after fee buffer and estimated gas."""
    notional = float(trade_usd)
    if notional <= 0.0:
        return -100.0
    buffer = _min_net_edge_fee_buffer_pct() if fee_buffer_pct is None else max(0.0, float(fee_buffer_pct))
    effective_gross = max(0.0, float(expected_gross_edge_pct) - buffer)
    gross_profit_usd = notional * (effective_gross / 100.0)
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
    """Emit active net-edge threshold once per process so ops can confirm the filter is armed."""
    global _MIN_NET_EDGE_POLICY_LOGGED
    if _MIN_NET_EDGE_POLICY_LOGGED:
        return
    _MIN_NET_EDGE_POLICY_LOGGED = True
    floor = _min_net_edge_floor_pct()
    planning_gwei = _planning_gas_gwei_for_net_edge()
    fee_buf = _min_net_edge_fee_buffer_pct()
    dirs = ",".join(sorted(_MIN_NET_EDGE_ENTRY_DIRECTIONS))
    print(
        f"[nanoclaw] MIN_NET_EDGE_ACTIVE | threshold={floor:.2f}% net after gas "
        f"| fee_buffer={fee_buf:.2f}% | planning_gas={planning_gwei:.0f}gwei "
        f"| directions={dirs} | stage={stage}"
    )


def _signal_label_for_edge_log(decision: TradeDecision) -> str:
    strength = decision.signal_strength
    if strength is not None:
        return f"{float(strength):.3f}"
    return "n/a"


def _low_edge_rejection_log_line(
    *,
    expected_net_pct: float,
    signal: str,
    notional: float | None,
    floor_pct: float,
    direction: str,
    stage: str,
) -> str:
    notional_s = "n/a" if notional is None or float(notional) <= 0.0 else f"${float(notional):.2f}"
    return (
        f"[nanoclaw] LOW EDGE REJECTED | expected_net={expected_net_pct:.2f}% | notional={notional_s} "
        f"| floor={floor_pct:.2f}% | signal={signal} | direction={direction} | stage={stage}"
    )


def _reject_if_low_expected_net_edge(
    decision: TradeDecision,
    *,
    trade_usd: float | None,
    gas_gwei: float,
    log_skip: Callable[[str], None] | None = None,
    stage: str = "planning",
) -> bool:
    """Log and return True when the entry should be blocked for low expected net edge."""
    direction = str(decision.direction or "").strip().upper()
    if direction not in _MIN_NET_EDGE_ENTRY_DIRECTIONS:
        return False
    min_floor = _min_net_edge_floor_pct()
    fee_buf = _min_net_edge_fee_buffer_pct()
    signal_s = _signal_label_for_edge_log(decision)
    notional = float(trade_usd) if trade_usd is not None else 0.0
    if notional <= 0.0:
        reason = "below_min_net_edge (missing_notional)"
        if log_skip is not None:
            log_skip(f"low_expected_edge ({reason}; floor={min_floor:.2f}%)")
        print(
            _low_edge_rejection_log_line(
                expected_net_pct=-100.0,
                signal=signal_s,
                notional=None,
                floor_pct=min_floor,
                direction=direction,
                stage=stage,
            )
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
    effective_gross = _effective_gross_edge_after_fee_buffer(gross_pct)
    reason = f"below_min_net_edge (floor={min_floor:.2f}%)"
    if log_skip is not None:
        log_skip(
            f"low_expected_edge (expected_net_return_pct={expected_net:.2f}% < {min_floor:.2f}% "
            f"after gas; effective_gross={effective_gross:.2f}% fee_buffer={fee_buf:.2f}% "
            f"notional=${notional:.2f})"
        )
    print(
        _low_edge_rejection_log_line(
            expected_net_pct=expected_net,
            signal=signal_s,
            notional=notional,
            floor_pct=min_floor,
            direction=direction,
            stage=stage,
        )
    )
    return True


def _decision_blocked_by_min_net_edge(
    decision: TradeDecision,
    *,
    trade_usd: float | None,
    gas_gwei: float,
    log_skip: Callable[[str], None],
    stage: str = "planning",
) -> tuple[bool, float]:
    """Early decision-flow gate for X-Signal / main entry (before dust defer / execution)."""
    direction = str(decision.direction or "").strip().upper()
    if direction not in _MIN_NET_EDGE_ENTRY_DIRECTIONS:
        return False, 0.0
    notional = float(trade_usd) if trade_usd is not None else 0.0
    _, expected_net = trade_passes_min_net_edge(
        decision,
        trade_usd=notional,
        gas_gwei=float(gas_gwei),
    )
    blocked = _reject_if_low_expected_net_edge(
        decision,
        trade_usd=trade_usd,
        gas_gwei=gas_gwei,
        log_skip=log_skip,
        stage=stage,
    )
    return blocked, expected_net


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

    Keep consistent with X-signal risk heuristics (combined stables + WMATIC liquidity risk).
    """
    try:
        return str(
            signal_module._x_signal_buy_risk_level(
                usdt=float(balances.usdt),
                usdc=float(balances.usdc),
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


def _clear_defensive_pause_window(state: dict) -> None:
    """End an active defensive pause (e.g. reduced HIGH-risk X-SIGNAL allowed this cycle)."""
    d = state.setdefault("defensive_pause", {})
    if int(d.get("remaining_cycles", 0) or 0) > 0:
        d["remaining_cycles"] = 0
        print(f"{runtime._nanolog()}Defensive pause window cleared (reduced HIGH-risk X-SIGNAL)")


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

def _main_strategy_stable_reserve_direction(balances: Balances) -> str:
    """
    WMATIC→stable for reserve / buffer rebuild.

    Prefer USDC when combined stables are below the X-SIGNAL high buffer (USDT+USDC spend gate),
    so rebuild feeds the bucket X-SIGNAL BUYs actually use.
    """
    if not bool(getattr(cfg, "MAIN_STRATEGY_RESERVE_PREFER_USDC", True)):
        return "WMATIC_TO_USDT"
    stable_usd = float(balances.usdt) + float(balances.usdc)
    high_trigger = float(getattr(cfg, "PROTECTION_FLUCTUATION_USDT_THRESHOLD", 12.0)) + 3.0
    if stable_usd + 1e-9 < high_trigger:
        return "WMATIC_TO_USDC"
    if float(balances.usdc) + 1e-9 < float(balances.usdt):
        return "WMATIC_TO_USDC"
    return "WMATIC_TO_USDT"


def select_main_strategy_trade(
    balances: Balances,
    current_price: float,
    *,
    state: dict | None = None,
    profit_signal: dict | None = None,
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
        reserve_dir = _main_strategy_stable_reserve_direction(balances)
        stable_out = "USDC" if reserve_dir == "WMATIC_TO_USDC" else "USDT"
        decision_log.log_main_strategy_decision(
            action="TAKE",
            reason="usdt_reserve_protection",
            direction=reserve_dir,
            notional_usd=notional,
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=wmatic_value_usd,
            state=state,
        )
        return TradeDecision(
            direction=reserve_dir,
            amount_in=int(balances.wmatic * MAIN_STRATEGY_RESERVE_SELL_FRACTION * 1e18),
            message=(
                f"🔄 STABLE RESERVE PROTECTION ({stable_out}): USDT=${balances.usdt:.2f} "
                f"USDC=${balances.usdc:.2f} | USDT target ${MAIN_STRATEGY_MIN_USDT_RESERVE:.0f}"
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

    # Small USD stack (~$5–$8): prefer controlled idle rotation before cut-loss (high token qty, low $).
    if _profit_take_wmatic_stack_low(wmatic_value_usd) or _wmatic_in_small_rotation_value_band(
        wmatic_value_usd
    ):
        idle_rotation = _main_strategy_idle_rotation_sell_decision(
            balances,
            current_price,
            state=state,
            profit_signal=profit_signal,
        )
        if idle_rotation is not None:
            return idle_rotation

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
        profit_signal=profit_signal,
    )
    if idle_rotation is not None:
        return idle_rotation

    defer_accum = _main_strategy_accumulate_deferred_reason(wmatic_value_usd, state)
    if defer_accum is not None:
        decision_log.log_main_strategy_decision(
            action="REJECT",
            reason="accumulate_deferred_anti_churn",
            direction="USDT_TO_WMATIC",
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=wmatic_value_usd,
            extra=defer_accum,
            state=state,
        )
        return TradeDecision(
            message=f"ℹ️ Main WMATIC buy deferred ({defer_accum})",
        )

    accumulate_size_multiplier = 1.0
    # Soft brake: reduce buy aggression when WMATIC is already elevated
    if wmatic_value_usd > 70:
        # Temporarily buy smaller size when stack is high
        accumulate_size_multiplier = 0.65
    if accumulate_size_multiplier < 1.0:
        trade_size = trade_size * accumulate_size_multiplier

    # Optional hard gate (uncomment if you want stronger control)
    # if wmatic_value_usd > 90:
    #     decision_log.log_main_strategy_decision(
    #         action="REJECT",
    #         reason="accumulation_paused_for_recovery",
    #         direction="USDT_TO_WMATIC",
    #         wmatic_balance=float(balances.wmatic),
    #         wmatic_usd=wmatic_value_usd,
    #         state=state,
    #     )
    #     return TradeDecision(
    #         message="ℹ️ Main WMATIC buy paused (accumulation_paused_for_recovery)",
    #     )

    gross_edge = plan_main_strategy_gross_edge_pct()
    buy_decision = TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message=f"🔄 Buying WMATIC (hold preferred) | Size: ${trade_size:.2f}",
        expected_gross_edge_pct=gross_edge,
    )
    _log_min_net_edge_policy_once(stage="main_strategy_plan")
    planning_gwei = _planning_gas_gwei_for_net_edge()
    if _reject_if_low_expected_net_edge(
        buy_decision,
        trade_usd=float(trade_size),
        gas_gwei=planning_gwei,
        log_skip=cs._log_trade_skipped,
        stage="main_strategy_plan",
    ):
        floor = _min_net_edge_floor_pct()
        decision_log.log_main_strategy_decision(
            action="REJECT",
            reason="below_min_net_edge",
            direction="USDT_TO_WMATIC",
            notional_usd=float(trade_size),
            wmatic_balance=float(balances.wmatic),
            wmatic_usd=wmatic_value_usd,
            extra=f"floor={floor:.2f}%",
            state=state,
        )
        return TradeDecision(
            message=(
                f"ℹ️ Main strategy skipped (expected net edge below {floor:.2f}% after gas)"
            ),
        )
    decision_log.log_main_strategy_decision(
        action="ACCEPT",
        reason="usdt_to_wmatic_accumulate",
        direction="USDT_TO_WMATIC",
        notional_usd=float(trade_size),
        wmatic_balance=float(balances.wmatic),
        wmatic_usd=wmatic_value_usd,
        state=state,
    )
    return buy_decision


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


# P2 / force / idle rotation thresholds — env-tunable via config.py (MAIN_STRATEGY_* in .env).
_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN = float(cfg.MAIN_STRATEGY_P2_WM_MIN_USD)
_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_NOTIONAL_FLOOR_USD = float(
    cfg.MAIN_STRATEGY_ROTATION_MIN_NOTIONAL_USD
)
_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH = float(cfg.MAIN_STRATEGY_P2_SIGNAL_MIN)
_PROFIT_TAKE_P2_RELIEF_LOG = "[nanoclaw] Main strategy small profit take allowed (P2 relief)"
_PROFIT_TAKE_P2_RELIEF_CHECK_LOG = "[nanoclaw] P2 relief check"
_PROFIT_TAKE_P2_RELIEF_OVERRIDE_ACTIVE_LOG = (
    "[nanoclaw] P2 RELIEF OVERRIDE ACTIVE | WMATIC=${wm} | notional=${notional} | "
    "bypassing min_notional"
)

# Aggressive gas protection (May 2026): unified rotation notional floors — default $8 healthy / $10 low+moderate.
_MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN = float(cfg.MAIN_STRATEGY_FORCE_WM_MIN_USD)
_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN = int(cfg.MAIN_STRATEGY_FORCE_CYCLES_MIN)
_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD = float(cfg.MAIN_STRATEGY_FORCE_NOTIONAL_FLOOR_USD)
_PROFIT_TAKE_FORCE_SMALL_LOG = (
    "[nanoclaw] FORCE small profit take | WMATIC=${wm:.2f} {stack_label}, "
    "no exit for {cycles} cycles | notional=${notional:.2f} | bypassing min_notional"
)

_MAIN_STRATEGY_LOW_WMATIC_USD_THRESHOLD = float(cfg.MAIN_STRATEGY_LOW_WM_USD_THRESHOLD)
_MAIN_STRATEGY_MODERATE_WMATIC_USD_THRESHOLD = float(cfg.MAIN_STRATEGY_MODERATE_WM_USD_THRESHOLD)
_MAIN_STRATEGY_LOW_WMATIC_P2_WM_MIN_USD = float(cfg.MAIN_STRATEGY_LOW_P2_WM_MIN_USD)
_MAIN_STRATEGY_LOW_WMATIC_P2_SIGNAL_MIN = float(cfg.MAIN_STRATEGY_LOW_P2_SIGNAL_MIN)
_MAIN_STRATEGY_LOW_WMATIC_FORCE_WM_MIN_USD = float(cfg.MAIN_STRATEGY_LOW_FORCE_WM_MIN_USD)
_MAIN_STRATEGY_LOW_WMATIC_FORCE_NOTIONAL_FLOOR_USD = float(cfg.MAIN_STRATEGY_LOW_ROTATION_MIN_NOTIONAL_USD)
_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN = int(cfg.MAIN_STRATEGY_LOW_FORCE_CYCLES_MIN)
_MAIN_STRATEGY_MODERATE_P2_WM_MIN_USD = float(cfg.MAIN_STRATEGY_MODERATE_P2_WM_MIN_USD)
_MAIN_STRATEGY_MODERATE_P2_SIGNAL_MIN = float(cfg.MAIN_STRATEGY_MODERATE_P2_SIGNAL_MIN)
_MAIN_STRATEGY_MODERATE_FORCE_WM_MIN_USD = float(cfg.MAIN_STRATEGY_MODERATE_FORCE_WM_MIN_USD)
_MAIN_STRATEGY_MODERATE_FORCE_CYCLES_MIN = int(cfg.MAIN_STRATEGY_MODERATE_FORCE_CYCLES_MIN)
_MAIN_STRATEGY_MODERATE_FORCE_NOTIONAL_FLOOR_USD = float(cfg.MAIN_STRATEGY_MODERATE_ROTATION_MIN_NOTIONAL_USD)
_MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD = float(cfg.MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD)
# Low-stables dust rebuild: sub-$8 WMATIC→stable when combined stables are critically low (reversible).
_MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_LOG = (
    "Main Strategy dust conversion to USDC for stable buffer rebuild"
)
_FE_STABLE_RUNWAY_TRIM_LOG = "[nanoclaw] FE STABLE RUNWAY TRIM"
_FE_STABLE_RUNWAY_DEFER_BUY_LOG = "[nanoclaw] FE STABLE RUNWAY | defer USDC→EQUITY BUY"
_MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_STATE_KEY = "low_stables_dust_rebuild"
_MAIN_STRATEGY_LONG_IDLE_CYCLES_LOW = int(cfg.MAIN_STRATEGY_LONG_IDLE_CYCLES_LOW)
_MAIN_STRATEGY_LONG_IDLE_CYCLES_MODERATE = int(cfg.MAIN_STRATEGY_LONG_IDLE_CYCLES_MODERATE)
_MAIN_STRATEGY_LONG_IDLE_CYCLES_HEALTHY = int(cfg.MAIN_STRATEGY_LONG_IDLE_CYCLES_HEALTHY)
_MAIN_STRATEGY_LONG_IDLE_NOTIONAL_FLOOR_USD = float(cfg.MAIN_STRATEGY_LONG_IDLE_NOTIONAL_FLOOR_USD)
_MAIN_STRATEGY_LONG_IDLE_FORCE_WM_MIN_USD = float(cfg.MAIN_STRATEGY_LONG_IDLE_FORCE_WM_MIN_USD)
_MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_HEALTHY = float(
    cfg.MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_HEALTHY
)
_MAIN_STRATEGY_LONG_IDLE_LOG = "[nanoclaw] MAIN_STRATEGY long idle fallback"

_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_CYCLES_MIN = 6
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_MIN_STABLE_USD = 50.0
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_MIN_SIGNAL = 0.75
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_CYCLES_MIN = 3
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_STABLE_USD = 30.0
_MAIN_STRATEGY_STABLE_ROTATION_FALLBACK_LOW_WM_MIN_SIGNAL = 0.60
_MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_LOW = float(cfg.MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_LOW)
_MAIN_STRATEGY_IDLE_ROTATION_NOTIONAL_FLOOR_LOW = float(cfg.MAIN_STRATEGY_IDLE_ROTATION_NOTIONAL_FLOOR_LOW)

# Mild-loss rotation: same $ floor as P2/force; disabled when capped sell cannot reach rotation min.
_MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MIN_PCT = float(cfg.MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MIN_PCT)
_MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MAX_PCT = float(cfg.MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MAX_PCT)
_MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MIN_USD = float(cfg.MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MIN_USD)
_MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MAX_USD = float(cfg.MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MAX_USD)
_MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN = int(cfg.MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN)
_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD = float(cfg.MAIN_STRATEGY_ROTATION_MIN_NOTIONAL_USD)
_MAIN_STRATEGY_MILD_LOSS_IDLE_SELL_FRACTION = 0.30
_MAIN_STRATEGY_MILD_LOSS_IDLE_MAX_NOTIONAL_USD = float(cfg.MAIN_STRATEGY_MILD_LOSS_MAX_NOTIONAL_USD)
_MAIN_STRATEGY_MILD_LOSS_FAST_WM_MIN_QTY = float(cfg.MAIN_STRATEGY_MILD_LOSS_FAST_WM_MIN_QTY)
_MAIN_STRATEGY_MILD_LOSS_FAST_MAX_NOTIONAL_USD = float(cfg.MAIN_STRATEGY_MILD_LOSS_MAX_NOTIONAL_USD)
_MAIN_STRATEGY_MILD_LOSS_IDLE_LOG = (
    "[nanoclaw] MAIN_STRATEGY mild-loss idle rotation ALLOWED | "
    "gain_pct={gain:.2f}% | wmatic_usd=${wm:.2f} | notional≈${notional:.2f} | "
    "cycles_since_exit={cycles} | capped_small_sell=True"
)
_MAIN_STRATEGY_IDLE_ROTATION_ALLOWED_LOG = (
    "[nanoclaw] MAIN_STRATEGY small idle rotation ALLOWED | "
    "wmatic_usd=${wm:.2f} | notional≈${notional:.2f} | cycles_since_exit={cycles} | "
    "path={path} | gain_pct={gain}"
)
_MAIN_STRATEGY_SMALL_IDLE_ROTATION_TRIGGERED_LOG = (
    "[Main Strategy] Small idle rotation triggered | WMATIC=${wm:.2f} | "
    "notional=${notional:.2f} | reason={reason}"
)
_MAIN_STRATEGY_MILD_LOSS_FAST_LOG = (
    "[Main Strategy] Mild-loss fast rotation | WMATIC=${wm:.2f} | "
    "notional=${notional:.2f} | reason=accelerate_recovery"
)
_MAIN_STRATEGY_MILD_LOSS_ROTATION_MIN_NOTIONAL_BYPASS_LOG = (
    "[Main Strategy] Mild-loss rotation executing (bypassed min_notional for recovery)"
)
_MAIN_STRATEGY_MILD_LOSS_RECOVERY_BYPASS_ACTIVE_LOG = (
    "[nanoclaw] MILD-LOSS RECOVERY BYPASS ACTIVE | path={path} | WMATIC=${wm:.2f} | "
    "notional=${notional:.2f} | gain_pct={gain}% | cycles_since_exit={cycles} | "
    "bypassing min_notional=${min_trade:.2f}"
)
_MAIN_STRATEGY_STATUS_LOG = "[nanoclaw] MAIN_STRATEGY_STATUS"
_MAIN_STRATEGY_OUTCOME_LOG = "[nanoclaw] MAIN_STRATEGY_OUTCOME"
_STABLE_ROTATION_FALLBACK_LOG = (
    "[nanoclaw] Signal-Driven Rotation: stable fallback | cycles_idle={cycles} | "
    "stables=${stable:.2f} | X-SIGNAL BUY eligible"
)


def _pnl_recovery_mode_active() -> bool:
    """Shared recovery posture for main-strategy rotation guards."""
    if bool(getattr(cfg, "MAIN_STRATEGY_PNL_RECOVERY_MODE", False)):
        return True
    return bool(getattr(cfg, "PNL_RECOVERY_MODE", False))


def _main_strategy_rotation_recovery_strict() -> bool:
    """True when idle/P2/mild-loss paths should use stricter notional + cycle floors."""
    if _pnl_recovery_mode_active():
        return True
    threshold = float(getattr(cfg, "MAIN_STRATEGY_RECOVERY_MAX_COPY_PCT_THRESHOLD", 0.06))
    if threshold <= 0.0:
        return False
    try:
        mcp = load_cycle_control().max_copy_trade_pct
        if mcp is not None and float(mcp) + 1e-9 <= threshold:
            return True
    except Exception:
        pass
    return False


def _recovery_rotation_min_notional_usd() -> float:
    """Minimum WMATIC→stable notional during recovery (blocks $2–$5 gas-negative micro exits)."""
    return float(getattr(cfg, "MAIN_STRATEGY_PNL_RECOVERY_IDLE_MIN_NOTIONAL_USD", 8.0))


def _recovery_long_idle_notional_floor_usd() -> float:
    """Long-idle micro floor — raised from $1.35 during recovery."""
    base = float(_MAIN_STRATEGY_LONG_IDLE_NOTIONAL_FLOOR_USD)
    if not _main_strategy_rotation_recovery_strict():
        return base
    recovery_floor = float(getattr(cfg, "MAIN_STRATEGY_PNL_RECOVERY_ROTATION_MIN_NOTIONAL_USD", 8.0))
    return max(base, recovery_floor)


def _recovery_idle_cycle_bonus() -> int:
    """Extra cycles before low-stack / long-idle micro rotations during recovery."""
    if not _main_strategy_rotation_recovery_strict():
        return 0
    return max(0, int(getattr(cfg, "MAIN_STRATEGY_PNL_RECOVERY_LONG_IDLE_CYCLE_BONUS", 3)))


# CRITICAL (Signal-Driven Rotation profitability): on-chain fill rate for X-SIGNAL USDC→equity BUYs.
# Without reliable fallback execution + STF backoff, selected signals burn gas and never rotate capital.
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


def _profit_take_mild_loss_gain_pct(profit_signal: dict | None) -> float | None:
    """Return gain_pct when open trade is HOLD in the mild-loss rotation band (~-7% to -1%)."""
    if profit_signal is None:
        return None
    if str(profit_signal.get("reason") or "").strip().upper() != "HOLD":
        return None
    try:
        gain = float(profit_signal.get("gain_pct", 0) or 0)
    except (TypeError, ValueError):
        return None
    if float(_MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MIN_PCT) <= gain <= float(
        _MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MAX_PCT
    ):
        return gain
    return None


def _wmatic_in_small_rotation_value_band(wm_equiv_usd: float) -> bool:
    wm = float(wm_equiv_usd)
    return wm + 1e-9 >= float(_MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MIN_USD) and wm <= float(
        _MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MAX_USD
    )


def _main_strategy_mild_loss_rotation_min_notional_bypass_allowed(
    decision: TradeDecision,
    *,
    balances: Balances,
    current_price_usd: float,
    min_trade_usd: float,
    profit_signal: dict | None = None,
    state: dict | None = None,
) -> bool:
    """Allow mild-loss recovery below global MIN_TRADE_USD when notional is in the $8–$9.99 window.

    Qualifies when WMATIC is in the $5–$10 mild-loss band, unrealized gain is ~-7% to -1%,
    and ``cycles_since_exit`` meets ``MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN``. Does not
    re-open sub-$8 auto-generated idle sells (those fail ``_main_strategy_mild_loss_idle_context``).
    Blocked during recovery strict mode when notional would stay below the recovery floor.
    """
    if not _main_strategy_mild_loss_enabled():
        return False
    direction = str(decision.direction or "").strip().upper()
    if direction not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    eff_min = float(min_trade_usd)
    if eff_min <= 0.0:
        return False
    notional_usd = _decision_notional_usd(decision, current_price_usd=current_price_usd)
    if notional_usd is None or notional_usd + 1e-9 >= eff_min:
        return False
    wm_equiv_usd = float(balances.wmatic) * float(current_price_usd)
    if not _wmatic_in_small_rotation_value_band(wm_equiv_usd):
        return False
    if _profit_take_mild_loss_gain_pct(profit_signal) is None:
        return False
    if int(_profit_take_cycles_since_exit(state)) < int(_MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN):
        return False
    floor_usd = float(_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD)
    if notional_usd + 1e-9 < floor_usd:
        return False
    if _main_strategy_rotation_recovery_strict():
        recovery_min = _recovery_rotation_min_notional_usd()
        if notional_usd + 1e-9 < recovery_min:
            return False
    return True


def _main_strategy_mild_loss_enabled() -> bool:
    return bool(getattr(cfg, "MAIN_STRATEGY_MILD_LOSS_ENABLED", True))


def _main_strategy_mild_loss_fast_rotation_eligible(
    profit_signal: dict | None,
    wm_equiv_usd: float,
    wmatic_qty: float,
    balances: Balances,
) -> bool:
    """Mild-loss band + high token qty + healthy USDT — rotate after min idle cycle if notional ≥ rotation floor."""
    # Recovery: disable 1-cycle fast path — gas-negative micro exits are worse than waiting.
    if _main_strategy_rotation_recovery_strict():
        return False
    if not _main_strategy_mild_loss_enabled():
        return False
    if _profit_take_mild_loss_gain_pct(profit_signal) is None:
        return False
    if not _wmatic_in_small_rotation_value_band(wm_equiv_usd):
        return False
    if float(wmatic_qty) + 1e-9 <= float(_MAIN_STRATEGY_MILD_LOSS_FAST_WM_MIN_QTY):
        return False
    if float(balances.usdt) + 1e-9 < float(MAIN_STRATEGY_MIN_USDT_RESERVE):
        return False
    rot_min = float(_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD)
    cap = min(
        float(_MAIN_STRATEGY_MILD_LOSS_FAST_MAX_NOTIONAL_USD),
        float(wm_equiv_usd) * float(_MAIN_STRATEGY_MILD_LOSS_IDLE_SELL_FRACTION),
    )
    return cap + 1e-9 >= rot_min


def _main_strategy_mild_loss_idle_context(
    profit_signal: dict | None,
    wm_equiv_usd: float,
    cycles_since_exit: int,
    *,
    balances: Balances | None = None,
    wmatic_qty: float | None = None,
) -> bool:
    """Small stack + mild unrealized loss + idle cycles (or fast path) when sell notional ≥ rotation floor."""
    if not _main_strategy_mild_loss_enabled():
        return False
    if _profit_take_mild_loss_gain_pct(profit_signal) is None:
        return False
    if not _wmatic_in_small_rotation_value_band(wm_equiv_usd):
        return False
    if (
        balances is not None
        and wmatic_qty is not None
        and _main_strategy_mild_loss_fast_rotation_eligible(
            profit_signal, wm_equiv_usd, wmatic_qty, balances
        )
    ):
        return True
    if int(cycles_since_exit) < int(_MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN):
        return False
    rot_min = float(_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD)
    cap = min(
        float(_MAIN_STRATEGY_MILD_LOSS_IDLE_MAX_NOTIONAL_USD),
        float(wm_equiv_usd) * float(_MAIN_STRATEGY_MILD_LOSS_IDLE_SELL_FRACTION),
    )
    return cap + 1e-9 >= rot_min


def _main_strategy_mild_loss_recovery_overrides_x_signal_p2_defer(
    profit_signal: dict | None,
    wm_equiv_usd: float,
    *,
    balances: Balances,
    state: dict | None,
) -> bool:
    """Mild-loss recovery may bypass X-Signal P2 defer when HOLD is in band and cycles qualify."""
    if not _main_strategy_mild_loss_enabled():
        return False
    if _profit_take_mild_loss_gain_pct(profit_signal) is None:
        return False
    if not _wmatic_in_small_rotation_value_band(wm_equiv_usd):
        return False
    return int(_profit_take_cycles_since_exit(state)) >= int(
        _MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN
    )


def _log_mild_loss_recovery_min_notional_bypass(
    *,
    wm_equiv_usd: float,
    notional_usd: float,
    min_trade_usd: float,
    profit_signal: dict | None = None,
    state: dict | None = None,
    path: str,
) -> None:
    """Structured log when a small mild-loss recovery rotation clears MIN_TRADE_USD."""
    gain = _profit_take_mild_loss_gain_pct(profit_signal)
    gain_s = f"{gain:.2f}" if gain is not None else "n/a"
    cycles = _profit_take_cycles_since_exit(state)
    print(
        _MAIN_STRATEGY_MILD_LOSS_RECOVERY_BYPASS_ACTIVE_LOG.format(
            path=path,
            wm=wm_equiv_usd,
            notional=notional_usd,
            gain=gain_s,
            cycles=cycles,
            min_trade=min_trade_usd,
        )
    )
    print(_MAIN_STRATEGY_MILD_LOSS_ROTATION_MIN_NOTIONAL_BYPASS_LOG)


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
    if (
        wmatic_usd_equiv is not None
        and _profit_take_mild_loss_gain_pct(profit_signal) is not None
        and _wmatic_in_small_rotation_value_band(float(wmatic_usd_equiv))
    ):
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
    Tiered floors: low 0.45, moderate 0.50, healthy 0.55 (see ``_profit_take_p2_signal_min``).
    When ``wmatic_usd_equiv`` is unknown, use the healthy default (0.55).
    """
    wm_min = float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN)
    profit_signal = _profit_signal_for_relief_scoring(
        profit_signal,
        wmatic_usd_equiv=wmatic_usd_equiv,
    )
    if wmatic_usd_equiv is not None:
        floor = _profit_take_p2_signal_min(float(wmatic_usd_equiv))
    else:
        floor = float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH)

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
            if (
                wmatic_usd_equiv is not None
                and _profit_take_mild_loss_gain_pct(profit_signal) is not None
                and _wmatic_in_small_rotation_value_band(float(wmatic_usd_equiv))
            ):
                return _round_relief_signal_strength(floor)
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


def _low_stables_dust_rebuild_enabled() -> bool:
    return bool(getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_ENABLED", True))


def _low_stables_dust_rebuild_state(state: dict | None) -> dict:
    if state is None:
        return {}
    return state.setdefault(_MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_STATE_KEY, {})


def _low_stables_dust_rebuild_bump_cycle(state: dict) -> int:
    d = _low_stables_dust_rebuild_state(state)
    n = int(d.get("cycle_count", 0) or 0) + 1
    d["cycle_count"] = n
    return n


def _low_stables_dust_rebuild_rate_ok(state: dict | None) -> bool:
    """Cooldown between *new* rebuild plans after a successful swap; pending may always retry."""
    if state is None:
        return True
    d = _low_stables_dust_rebuild_state(state)
    if bool(d.get("pending_execution")):
        return True
    cooldown = max(1, int(getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_CYCLE_COOLDOWN", 3)))
    last = int(d.get("last_executed_cycle", 0) or 0)
    current = int(d.get("cycle_count", 0) or 0)
    if last <= 0:
        return True
    return (current - last) >= cooldown


def _low_stables_dust_rebuild_reconcile_state(state: dict) -> None:
    """Drop legacy planning-only cooldown markers (pre-9c8d38e1) that blocked execution retries."""
    d = _low_stables_dust_rebuild_state(state)
    if bool(d.get("pending_execution")):
        return
    last_allowed = int(d.get("last_allowed_cycle", 0) or 0)
    last_executed = int(d.get("last_executed_cycle", 0) or 0)
    if last_allowed > 0 and last_executed < last_allowed:
        d.pop("last_allowed_cycle", None)


def _record_low_stables_dust_rebuild_pending(state: dict) -> None:
    """Planning approved a dust rebuild; execution may retry until swap succeeds."""
    d = _low_stables_dust_rebuild_state(state)
    d["pending_execution"] = True


def _record_low_stables_dust_rebuild_executed(state: dict) -> None:
    """Consume cooldown only after a successful WMATIC→stable rebuild swap."""
    d = _low_stables_dust_rebuild_state(state)
    cycle = int(d.get("cycle_count", 0) or 0)
    d["last_executed_cycle"] = cycle
    d["last_allowed_cycle"] = cycle
    d.pop("pending_execution", None)


def _record_low_stables_dust_rebuild_allowed(state: dict) -> None:
    """Backward-compatible alias for planning-time pending flag."""
    _record_low_stables_dust_rebuild_pending(state)


def _fe_stable_runway_buy_block_context(balances: Balances) -> dict[str, float] | None:
    """FE-heavy book below runway target: block USDC→EQUITY / X-SIGNAL BUY (stables < target)."""
    if not bool(getattr(cfg, "FE_STABLE_RUNWAY_ENABLED", True)):
        return None
    stable_usd = float(balances.usdt) + float(balances.usdc)
    target_stable = float(getattr(cfg, "FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0))
    if stable_usd + 1e-9 >= target_stable:
        return None
    min_portfolio = float(
        getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MIN_PORTFOLIO_USD", 130.0)
    )
    total = float(balances.total_portfolio_usd)
    if total <= min_portfolio:
        return None
    fe_usd = float(balances.followed_equity_usd)
    if total <= 0.0:
        return None
    fe_share = fe_usd / total
    min_fe_share = float(getattr(cfg, "FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55))
    if fe_share + 1e-9 < min_fe_share:
        return None
    return {
        "stable_usd": stable_usd,
        "fe_share": fe_share,
        "target_stable_usd": target_stable,
        "fe_usd": fe_usd,
    }


def _fe_stable_runway_context(
    balances: Balances,
    *,
    wmatic_usd: float | None = None,
) -> dict[str, float] | None:
    """Metrics when FE-heavy book needs stable runway trim (WMATIC rebuild path absent)."""
    fe_buy = _fe_stable_runway_buy_block_context(balances)
    if fe_buy is None:
        return None
    stable_usd = float(fe_buy["stable_usd"])
    max_stable = float(getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD", 15.0))
    if stable_usd + 1e-9 >= max_stable:
        return None
    rebuild_floor = float(
        getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_NOTIONAL_FLOOR_USD", 5.0)
    )
    if wmatic_usd is not None:
        if float(wmatic_usd) + 1e-9 >= rebuild_floor:
            return None
    elif float(balances.wmatic) > 0.0:
        return None
    return fe_buy


def _fe_stable_runway_buy_block_active(
    balances: Balances,
    *,
    wmatic_usd: float | None = None,
) -> bool:
    del wmatic_usd  # buy guard is stable/fe-share only; trim context uses WMATIC separately
    return _fe_stable_runway_buy_block_context(balances) is not None


def _log_fe_stable_runway_trim(
    *,
    sym: str,
    sell_fraction: float,
    stable_usd: float,
    fe_share: float,
    target_stable_usd: float,
) -> None:
    print(
        f"{_FE_STABLE_RUNWAY_TRIM_LOG} | sym={sym} | sell_fraction={float(sell_fraction):.4f} | "
        f"stable_usd={float(stable_usd):.2f} | fe_share={float(fe_share):.2f} | "
        f"target_stable_usd={float(target_stable_usd):.2f}"
    )


def _log_fe_stable_runway_defer_buy(*, stable_usd: float, fe_share: float) -> None:
    print(
        f"{_FE_STABLE_RUNWAY_DEFER_BUY_LOG} | stable_usd={float(stable_usd):.2f} | "
        f"fe_share={float(fe_share):.2f}"
    )


_OPERATING_RESERVE_LOG = "[nanoclaw] OPERATING RESERVE FLOOR | defer new entry"


def _operating_reserve_seed_usd(balances: Balances) -> float:
    explicit = float(getattr(cfg, "STAGE_SEED_USD", 0.0) or 0.0)
    if explicit > 0.0:
        return explicit
    return max(float(balances.total_portfolio_usd), 0.0)


def _operating_reserve_buy_block_context(balances: Balances) -> dict[str, float] | None:
    """Block new entries when stables fall below seed × OPERATING_RESERVE_PCT."""
    if not bool(getattr(cfg, "OPERATING_RESERVE_ENABLED", True)):
        return None
    pct = float(getattr(cfg, "OPERATING_RESERVE_PCT", 10.0))
    if pct <= 0.0:
        return None
    seed = _operating_reserve_seed_usd(balances)
    if seed <= 0.0:
        return None
    floor_usd = seed * (pct / 100.0)
    stable_usd = float(balances.usdt) + float(balances.usdc)
    if stable_usd + 1e-9 >= floor_usd:
        return None
    return {
        "stable_usd": stable_usd,
        "reserve_floor_usd": floor_usd,
        "seed_usd": seed,
        "reserve_pct": pct,
    }


def _operating_reserve_buy_block_active(balances: Balances) -> bool:
    return _operating_reserve_buy_block_context(balances) is not None


def _log_operating_reserve_defer(*, stable_usd: float, reserve_floor_usd: float, seed_usd: float) -> None:
    print(
        f"{_OPERATING_RESERVE_LOG} | stable_usd={float(stable_usd):.2f} | "
        f"reserve_floor={float(reserve_floor_usd):.2f} | seed={float(seed_usd):.2f}"
    )


def _apply_low_stables_rebuild_rotation_precedence(
    rotation_first: bool,
    *,
    balances: Balances,
    state: dict | None,
    wmatic_usd: float | None = None,
) -> bool:
    """Stable-first: defer rotation-priority X-SIGNAL BUY when stables rebuild is urgent."""
    if not rotation_first:
        return False
    fe_buy = _fe_stable_runway_buy_block_context(balances)
    if fe_buy is not None:
        _log_fe_stable_runway_defer_buy(
            stable_usd=float(fe_buy["stable_usd"]),
            fe_share=float(fe_buy["fe_share"]),
        )
        return False
    if not _low_stables_dust_rebuild_enabled():
        return rotation_first
    stable_usd = float(balances.usdt) + float(balances.usdc)
    max_stable = float(getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD", 15.0))
    min_portfolio = float(
        getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MIN_PORTFOLIO_USD", 130.0)
    )
    if stable_usd + 1e-9 >= max_stable:
        return rotation_first
    if float(balances.total_portfolio_usd) <= min_portfolio:
        return rotation_first
    print(
        f"{runtime._nanolog()}Signal-Driven Rotation: X-Signal BUY deferred — "
        "low-stables stable rebuild has cycle priority"
    )
    return False


def _main_strategy_low_stables_dust_rebuild_execution_bypass(
    state: dict | None,
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
    min_trade_usd: float,
) -> bool:
    """Execution-time MIN_TRADE_USD bypass for a planning-approved low-stables dust rebuild."""
    if state is None or decision_notional_usd is None or min_trade_usd <= 0:
        return False
    d = _low_stables_dust_rebuild_state(state)
    if not bool(d.get("pending_execution")):
        return False
    direction = str(decision.direction or "").strip().upper()
    if direction not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    rebuild_floor = float(
        getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_NOTIONAL_FLOOR_USD", 5.0)
    )
    if float(decision_notional_usd) + 1e-9 < rebuild_floor:
        return False
    if float(decision_notional_usd) + 1e-9 >= float(min_trade_usd):
        return False
    return True


def _clear_low_stables_dust_rebuild_pending(state: dict | None) -> None:
    if state is None:
        return
    d = _low_stables_dust_rebuild_state(state)
    d.pop("pending_execution", None)


def _main_strategy_low_stables_dust_rebuild_eligible(
    decision: TradeDecision,
    *,
    balances: Balances,
    current_price_usd: float,
) -> bool:
    """Core gates for low-stables dust rebuild (stables, portfolio, notional band, direction)."""
    if not _low_stables_dust_rebuild_enabled():
        return False
    direction = str(decision.direction or "").strip().upper()
    if direction not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False

    stable_usd = float(balances.usdt) + float(balances.usdc)
    max_stable = float(getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD", 15.0))
    if stable_usd + 1e-9 >= max_stable:
        return False

    min_portfolio = float(
        getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MIN_PORTFOLIO_USD", 130.0)
    )
    if float(balances.total_portfolio_usd) <= min_portfolio:
        return False

    notional_usd = _decision_notional_usd(decision, current_price_usd=current_price_usd)
    rebuild_floor = float(
        getattr(cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_NOTIONAL_FLOOR_USD", 5.0)
    )
    dust_floor = float(_MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD)
    if notional_usd is None:
        return False
    if notional_usd + 1e-9 < rebuild_floor:
        return False
    if notional_usd + 1e-9 >= dust_floor:
        return False
    return True


def _main_strategy_low_stables_dust_rebuild_override_active(
    decision: TradeDecision,
    *,
    balances: Balances,
    current_price_usd: float,
    state: dict | None = None,
) -> bool:
    """
    Exception path when MAIN_STRATEGY would dust-defer a small WMATIC→stable exit but stables are critical.

    Only applies below the normal ``MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD`` floor (default $8), down to
    ``MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_NOTIONAL_FLOOR_USD`` (default $5). Normal dust thresholds unchanged.
    """
    if not _main_strategy_low_stables_dust_rebuild_eligible(
        decision,
        balances=balances,
        current_price_usd=current_price_usd,
    ):
        return False
    if not _low_stables_dust_rebuild_rate_ok(state):
        return False
    return True


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


# === TEMPORARY PnL RECOVERY MODE (May 24, 2026) ===
# Reduce aggressive WMATIC accumulation while we stabilize the portfolio.
# Revert once total > $110 and stable_usd stays healthy.
_MAIN_STRATEGY_ACCUMULATE_MAX_WMATIC_USD = 18.0  # was 22
_MAIN_STRATEGY_ACCUMULATE_COOLDOWN_CYCLES = 8  # was 6 (wait longer after exits)
MAIN_STRATEGY_ACCUMULATE_MAX_WMATIC_USD = _MAIN_STRATEGY_ACCUMULATE_MAX_WMATIC_USD
MAIN_STRATEGY_ACCUMULATE_COOLDOWN_CYCLES = _MAIN_STRATEGY_ACCUMULATE_COOLDOWN_CYCLES


def _main_strategy_accumulate_deferred_reason(
    wmatic_value_usd: float,
    state: dict | None,
) -> str | None:
    """Return a defer reason when USDT→WMATIC would add churn; ``None`` if accumulate is OK."""
    cooldown = int(_MAIN_STRATEGY_ACCUMULATE_COOLDOWN_CYCLES)
    if cooldown > 0:
        cycles = _profit_take_cycles_since_exit(state)
        if cycles < cooldown:
            return (
                f"accumulate_cooldown ({cycles}/{cooldown} cycles since WMATIC→stable exit)"
            )
    cap = float(_MAIN_STRATEGY_ACCUMULATE_MAX_WMATIC_USD)
    if cap > 0.0 and float(wmatic_value_usd) + 1e-9 >= cap:
        return f"wmatic_at_or_above_cap (${wmatic_value_usd:.2f} >= ${cap:.2f})"
    return None


def _profit_take_wmatic_stack_low(wm_equiv_usd: float) -> bool:
    """Signal-Driven Rotation (May 2026): stack below $7 — use relaxed P2/force thresholds."""
    return float(wm_equiv_usd) + 1e-9 < float(_MAIN_STRATEGY_LOW_WMATIC_USD_THRESHOLD)


def _profit_take_wmatic_stack_moderate(wm_equiv_usd: float) -> bool:
    """Stack $7–$15: between depleted and healthy — still reduce WMATIC-centric gates."""
    wm = float(wm_equiv_usd)
    return wm + 1e-9 >= float(_MAIN_STRATEGY_LOW_WMATIC_USD_THRESHOLD) and wm + 1e-9 < float(
        _MAIN_STRATEGY_MODERATE_WMATIC_USD_THRESHOLD
    )


def _profit_take_stack_tier(wm_equiv_usd: float) -> str:
    """low | moderate | healthy — drives P2/force/idle thresholds (less WMATIC balance required)."""
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        return "low"
    if _profit_take_wmatic_stack_moderate(wm_equiv_usd):
        return "moderate"
    return "healthy"


def _profit_take_long_idle_cycles_min(wm_equiv_usd: float) -> int:
    tier = _profit_take_stack_tier(wm_equiv_usd)
    if tier == "low":
        base = int(_MAIN_STRATEGY_LONG_IDLE_CYCLES_LOW)
    elif tier == "moderate":
        base = int(_MAIN_STRATEGY_LONG_IDLE_CYCLES_MODERATE)
    else:
        base = int(_MAIN_STRATEGY_LONG_IDLE_CYCLES_HEALTHY)
    return base + _recovery_idle_cycle_bonus()


def _profit_take_long_idle_active(wm_equiv_usd: float, cycles_since_exit: int) -> bool:
    """Many cycles without WMATIC→stable exit — micro rotation / force within gas-safe bounds."""
    return int(cycles_since_exit) >= _profit_take_long_idle_cycles_min(wm_equiv_usd)


def _profit_take_p2_wm_stack_min_usd(wm_equiv_usd: float) -> float:
    tier = _profit_take_stack_tier(wm_equiv_usd)
    if tier == "low":
        return float(_MAIN_STRATEGY_LOW_WMATIC_P2_WM_MIN_USD)
    if tier == "moderate":
        return float(_MAIN_STRATEGY_MODERATE_P2_WM_MIN_USD)
    return float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN)


def _profit_take_p2_signal_min(wm_equiv_usd: float) -> float:
    tier = _profit_take_stack_tier(wm_equiv_usd)
    if tier == "low":
        return float(_MAIN_STRATEGY_LOW_WMATIC_P2_SIGNAL_MIN)
    if tier == "moderate":
        return float(_MAIN_STRATEGY_MODERATE_P2_SIGNAL_MIN)
    return float(_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH)


def _profit_take_force_wm_min_usd(
    wm_equiv_usd: float,
    *,
    cycles_since_exit: int = 0,
) -> float:
    tier = _profit_take_stack_tier(wm_equiv_usd)
    if tier == "low":
        base = float(_MAIN_STRATEGY_LOW_WMATIC_FORCE_WM_MIN_USD)
    elif tier == "moderate":
        base = float(_MAIN_STRATEGY_MODERATE_FORCE_WM_MIN_USD)
    else:
        base = float(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_WMATIC_USD_MIN)
    if _profit_take_long_idle_active(wm_equiv_usd, cycles_since_exit):
        return min(base, float(_MAIN_STRATEGY_LONG_IDLE_FORCE_WM_MIN_USD))
    return base


def _profit_take_force_cycles_min(wm_equiv_usd: float) -> int:
    tier = _profit_take_stack_tier(wm_equiv_usd)
    if tier == "low":
        base = int(_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN)
    elif tier == "moderate":
        base = int(_MAIN_STRATEGY_MODERATE_FORCE_CYCLES_MIN)
    else:
        base = int(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_CYCLES_MIN)
    return base + _recovery_idle_cycle_bonus()


def _profit_take_force_notional_floor_usd(
    wm_equiv_usd: float,
    *,
    cycles_since_exit: int = 0,
) -> float:
    tier = _profit_take_stack_tier(wm_equiv_usd)
    if _profit_take_wmatic_stack_low(wm_equiv_usd) and _profit_take_long_idle_active(
        wm_equiv_usd, cycles_since_exit
    ):
        return _recovery_long_idle_notional_floor_usd()
    if tier == "low":
        return float(_MAIN_STRATEGY_LOW_WMATIC_FORCE_NOTIONAL_FLOOR_USD)
    if tier == "moderate":
        return float(_MAIN_STRATEGY_MODERATE_FORCE_NOTIONAL_FLOOR_USD)
    return float(_MAIN_STRATEGY_FORCE_PROFIT_TAKE_NOTIONAL_FLOOR_USD)


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


def _main_strategy_idle_cycles_required(
    wm_equiv_usd: float,
    *,
    mild_loss_idle: bool,
    mild_loss_fast: bool = False,
) -> int:
    """Idle cycles before WMATIC→stable micro rotation (tiered; mild-loss / $5–$8 fast path)."""
    bonus = _recovery_idle_cycle_bonus()
    if mild_loss_fast:
        return 1 + bonus
    if mild_loss_idle:
        return int(_MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN) + bonus
    if _wmatic_in_small_rotation_value_band(wm_equiv_usd):
        return int(_MAIN_STRATEGY_LOW_WMATIC_FORCE_CYCLES_MIN) + bonus
    return _profit_take_force_cycles_min(wm_equiv_usd) + bonus


def _main_strategy_idle_rotation_sell_fraction(
    wm_equiv_usd: float,
    *,
    mild_loss_idle: bool = False,
    mild_loss_fast: bool = False,
) -> float:
    """Smaller sell slice when WMATIC stack is depleted — keeps rotation gas-efficient."""
    if mild_loss_idle:
        wm = max(float(wm_equiv_usd), 1e-9)
        frac = float(_MAIN_STRATEGY_MILD_LOSS_IDLE_SELL_FRACTION)
        max_notional = float(_MAIN_STRATEGY_MILD_LOSS_IDLE_MAX_NOTIONAL_USD)
        if mild_loss_fast:
            max_notional = min(
                max_notional,
                float(_MAIN_STRATEGY_MILD_LOSS_FAST_MAX_NOTIONAL_USD),
            )
        cap_frac = max_notional / wm
        return min(frac, cap_frac, float(MAIN_STRATEGY_RESERVE_SELL_FRACTION))
    if _profit_take_wmatic_stack_low(wm_equiv_usd):
        # ~32% on a ~$5.7 stack clears the $1.50 low-stack notional floor for idle rotation.
        return float(_MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_LOW)
    if _profit_take_stack_tier(wm_equiv_usd) == "healthy":
        return float(_MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_HEALTHY)
    return float(MAIN_STRATEGY_RESERVE_SELL_FRACTION)


def _main_strategy_idle_rotation_eligibility(
    balances: Balances,
    current_price: float,
    state: dict | None,
    *,
    profit_signal: dict | None = None,
) -> tuple[bool, str]:
    """Whether main strategy would emit an idle WMATIC→stable rotation sell this cycle."""
    wm_equiv = float(balances.wmatic) * float(current_price)
    if wm_equiv + 1e-9 >= float(MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD):
        return False, "wmatic_above_tp_band"
    cycles = _profit_take_cycles_since_exit(state)
    mild_loss_fast = _main_strategy_mild_loss_fast_rotation_eligible(
        profit_signal,
        wm_equiv,
        float(balances.wmatic),
        balances,
    )
    mild_loss_idle = _main_strategy_mild_loss_idle_context(
        profit_signal,
        wm_equiv,
        cycles,
        balances=balances,
        wmatic_qty=float(balances.wmatic),
    )
    force_wm_min = _profit_take_force_wm_min_usd(wm_equiv, cycles_since_exit=cycles)
    if mild_loss_idle:
        force_wm_min = min(force_wm_min, float(_MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MIN_USD))
    if wm_equiv + 1e-9 < force_wm_min:
        return False, f"wmatic_below_force_floor_${force_wm_min:.2f}"
    cycles_min = _main_strategy_idle_cycles_required(
        wm_equiv,
        mild_loss_idle=mild_loss_idle,
        mild_loss_fast=mild_loss_fast,
    )
    if cycles < cycles_min:
        return False, f"idle_cycles={cycles}/{cycles_min}"
    fraction = _main_strategy_idle_rotation_sell_fraction(
        wm_equiv,
        mild_loss_idle=mild_loss_idle,
        mild_loss_fast=mild_loss_fast,
    )
    notional = wm_equiv * fraction
    floor = _profit_take_force_notional_floor_usd(wm_equiv, cycles_since_exit=cycles)
    if mild_loss_idle:
        floor = min(floor, float(_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD))
    if notional + 1e-9 < floor:
        long_idle = _profit_take_long_idle_active(wm_equiv, cycles)
        return False, (
            f"notional_${notional:.2f}_below_${floor:.2f}"
            + (" (long_idle_not_met)" if long_idle else "")
            + (" (mild_loss_idle)" if mild_loss_idle else "")
        )
    if int(balances.wmatic * fraction * 1e18) <= 0:
        return False, "zero_amount_in"
    # Recovery: block all sub-floor idle/mild-loss/P2 micro rotations (including former $1.35 long-idle path).
    if _main_strategy_rotation_recovery_strict():
        recovery_min_notional = _recovery_rotation_min_notional_usd()
        if notional + 1e-9 < recovery_min_notional:
            return False, (
                f"pnl_recovery_micro_rotation_paused_${notional:.2f}_lt_${recovery_min_notional:.2f}"
            )
    if mild_loss_idle:
        if mild_loss_fast:
            return True, "eligible_mild_loss_fast_rotation"
        return True, "eligible_mild_loss_idle_rotation"
    if _profit_take_long_idle_active(wm_equiv, cycles):
        return True, "eligible_long_idle_micro_rotation"
    return True, "eligible"


def _main_strategy_idle_rotation_sell_decision(
    balances: Balances,
    current_price: float,
    *,
    state: dict | None = None,
    profit_signal: dict | None = None,
) -> TradeDecision | None:
    """Small WMATIC→stable exit after idle cycles — capital rotation without high WMATIC stack."""
    eligible, note = _main_strategy_idle_rotation_eligibility(
        balances,
        current_price,
        state,
        profit_signal=profit_signal,
    )
    if not eligible:
        return None
    wm_equiv = float(balances.wmatic) * float(current_price)
    cycles = _profit_take_cycles_since_exit(state)
    mild_loss_fast = _main_strategy_mild_loss_fast_rotation_eligible(
        profit_signal,
        wm_equiv,
        float(balances.wmatic),
        balances,
    )
    mild_loss_idle = _main_strategy_mild_loss_idle_context(
        profit_signal,
        wm_equiv,
        cycles,
        balances=balances,
        wmatic_qty=float(balances.wmatic),
    )
    fraction = _main_strategy_idle_rotation_sell_fraction(
        wm_equiv,
        mild_loss_idle=mild_loss_idle,
        mild_loss_fast=mild_loss_fast,
    )
    notional = wm_equiv * fraction
    tier = _profit_take_stack_tier(wm_equiv)
    rotation_reason = (
        "accelerate_recovery"
        if mild_loss_fast
        else "recover_mild_loss"
        if mild_loss_idle
        else "low_wmatic_idle_rotation"
        if tier == "low"
        else "moderate_wmatic_idle_rotation"
        if tier == "moderate"
        else "healthy_wmatic_idle_rotation"
    )
    long_idle = _profit_take_long_idle_active(wm_equiv, cycles)
    gain_pct = _profit_take_mild_loss_gain_pct(profit_signal)
    path = (
        "mild_loss_fast"
        if mild_loss_fast
        else "mild_loss_idle"
        if mild_loss_idle
        else "long_idle_micro"
        if long_idle
        else f"{tier}_stack_idle"
    )
    gain_s = f"{gain_pct:.2f}" if gain_pct is not None else "n/a"
    print(
        _MAIN_STRATEGY_IDLE_ROTATION_ALLOWED_LOG.format(
            wm=wm_equiv,
            notional=notional,
            cycles=cycles,
            path=path,
            gain=gain_s,
        )
    )
    print(
        f"{runtime._nanolog()}Main strategy idle rotation | wmatic_usd=${wm_equiv:.2f} | "
        f"stack_tier={tier} | cycles_since_exit={cycles} | long_idle={long_idle} | "
        f"mild_loss_idle={mild_loss_idle} | mild_loss_fast={mild_loss_fast} | "
        f"gain_pct={gain_pct if gain_pct is not None else 'n/a'} | "
        f"sell_fraction={fraction:.2f} | notional≈${notional:.2f} | note={note}"
    )
    if mild_loss_fast:
        print(
            _MAIN_STRATEGY_MILD_LOSS_FAST_LOG.format(
                wm=wm_equiv,
                notional=notional,
            )
        )
    if mild_loss_idle:
        print(
            _MAIN_STRATEGY_SMALL_IDLE_ROTATION_TRIGGERED_LOG.format(
                wm=wm_equiv,
                notional=notional,
                reason="recover_mild_loss",
            )
        )
    if mild_loss_idle and gain_pct is not None:
        print(
            _MAIN_STRATEGY_MILD_LOSS_IDLE_LOG.format(
                gain=gain_pct,
                wm=wm_equiv,
                notional=notional,
                cycles=cycles,
            )
        )
    if long_idle:
        print(
            f"{_MAIN_STRATEGY_LONG_IDLE_LOG} | tier={tier} | cycles={cycles} | "
            f"wmatic_usd=${wm_equiv:.2f} | micro_rotation_ready=True"
        )
    decision_log.log_main_strategy_decision(
        action="TAKE",
        reason=rotation_reason,
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
            f"🔄 Idle WMATIC rotation ({tier} stack: "
            f"${wm_equiv:.2f}, {cycles} cycles since exit"
            f"{', mild loss' if mild_loss_idle else ''}"
            f"{', fast recovery' if mild_loss_fast else ''}"
            f"{', long idle' if long_idle else ''})"
        ),
    )


def _main_strategy_quiet_blocker(
    balances: Balances,
    current_price: float,
    profit_signal: dict | None,
    state: dict | None,
) -> str:
    """Human-readable reason main strategy is quiet this cycle (reduces WMATIC-balance mystery)."""
    wm_usd = float(balances.wmatic) * float(current_price)
    cycles = _profit_take_cycles_since_exit(state)
    idle_eligible, idle_note = _main_strategy_idle_rotation_eligibility(
        balances,
        current_price,
        state,
        profit_signal=profit_signal,
    )
    if idle_eligible:
        return "idle_rotation_ready"
    if cycles < _profit_take_force_cycles_min(wm_usd):
        need = _profit_take_force_cycles_min(wm_usd) - cycles
        return f"waiting_idle_cycles (need {need} more)"
    if wm_usd + 1e-9 < _profit_take_force_wm_min_usd(wm_usd, cycles_since_exit=cycles):
        return "wmatic_below_force_floor"
    stable = float(balances.usdt) + float(balances.usdc)
    fb_cycles, fb_stable_min, _ = _main_strategy_stable_rotation_fallback_params(wm_usd)
    if cycles >= fb_cycles and stable + 1e-9 >= fb_stable_min:
        return "stable_fallback_or_xsignal_pending"
    pt_reason = str((profit_signal or {}).get("reason") or "").strip().upper()
    if pt_reason == "HOLD":
        return "profit_take_hold_no_exit_signal"
    if "notional" in idle_note:
        return idle_note
    return idle_note or "default_usdt_to_wmatic_or_deferred"


def _log_main_strategy_cycle_status(
    balances: Balances,
    current_price: float,
    profit_signal: dict | None,
    state: dict | None,
) -> None:
    """Signal-Driven Rotation (May 2026): per-cycle visibility into main-strategy activity vs quiet."""
    wm_usd = float(balances.wmatic) * float(current_price)
    tier = _profit_take_stack_tier(wm_usd)
    low = tier == "low"
    moderate = tier == "moderate"
    cycles = _profit_take_cycles_since_exit(state)
    long_idle = _profit_take_long_idle_active(wm_usd, cycles)
    long_idle_in = max(0, _profit_take_long_idle_cycles_min(wm_usd) - cycles)
    stable = float(balances.usdt) + float(balances.usdc)
    pt_reason = str((profit_signal or {}).get("reason") or "n/a").strip().upper()
    fb_cycles, fb_stable_min, fb_signal_min = _main_strategy_stable_rotation_fallback_params(wm_usd)
    fallback_ready = cycles >= fb_cycles and stable + 1e-9 >= fb_stable_min
    idle_eligible, idle_note = _main_strategy_idle_rotation_eligibility(
        balances,
        current_price,
        state,
        profit_signal=profit_signal,
    )
    force_cycles_min = _profit_take_force_cycles_min(wm_usd)
    p2_or_force_ready = cycles >= force_cycles_min and wm_usd + 1e-9 >= _profit_take_p2_wm_stack_min_usd(
        wm_usd
    )
    activity = "active_idle_rotation" if idle_eligible else (
        "active_p2_or_force"
        if p2_or_force_ready or long_idle
        else "quiet_accumulate_or_wait"
    )
    quiet_blocker = _main_strategy_quiet_blocker(balances, current_price, profit_signal, state)
    print(
        f"{_MAIN_STRATEGY_STATUS_LOG} | wmatic_usd=${wm_usd:.2f} | stack_tier={tier} | "
        f"low_wmatic_stack={low} | moderate_wmatic_stack={moderate} | "
        f"cycles_since_wm_exit={cycles} | long_idle_active={long_idle} | "
        f"cycles_to_long_idle={long_idle_in} | stables=${stable:.2f} | profit_take_reason={pt_reason} | "
        f"activity={activity} | quiet_blocker={quiet_blocker} | "
        f"idle_rotation_eligible={idle_eligible} | idle_rotation_note={idle_note} | "
        f"p2_wm_min=${_profit_take_p2_wm_stack_min_usd(wm_usd):.2f} | "
        f"p2_signal_min={_profit_take_p2_signal_min(wm_usd):.2f} | "
        f"force_wm_min=${_profit_take_force_wm_min_usd(wm_usd, cycles_since_exit=cycles):.2f} | "
        f"force_cycles_min={force_cycles_min} | "
        f"force_notional_floor=${_profit_take_force_notional_floor_usd(wm_usd, cycles_since_exit=cycles):.2f} | "
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
    profit_signal: dict | None = None,
    balances: Balances | None = None,
) -> bool:
    """TEMPORARY SPRINT FIX - May 2026: force small profit take when stack + idle cycles qualify.

    Signal-Driven Rotation (May 2026): tiered wm/cycle/notional floors ($8–$10 moderate+;
    $1.35 long-idle micro only when stack < $7). Reduces WMATIC-centric churn.
    """
    dir_u = str(direction or "").strip().upper()
    if dir_u not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    force_wm_min = _profit_take_force_wm_min_usd(
        wm_equiv_usd,
        cycles_since_exit=cycles_since_exit,
    )
    floor_usd = _profit_take_force_notional_floor_usd(
        wm_equiv_usd,
        cycles_since_exit=cycles_since_exit,
    )
    cycles_min = _profit_take_force_cycles_min(wm_equiv_usd)
    mild_loss_fast = False
    if balances is not None:
        mild_loss_fast = _main_strategy_mild_loss_fast_rotation_eligible(
            profit_signal,
            wm_equiv_usd,
            float(balances.wmatic),
            balances,
        )
    if _main_strategy_mild_loss_idle_context(
        profit_signal,
        wm_equiv_usd,
        cycles_since_exit,
        balances=balances,
        wmatic_qty=float(balances.wmatic) if balances is not None else None,
    ):
        cycles_min = 0 if mild_loss_fast else min(
            cycles_min, int(_MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN)
        )
        floor_usd = min(floor_usd, float(_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD))
    if wm_equiv_usd + 1e-9 < force_wm_min:
        return False
    if notional_usd + 1e-9 < floor_usd:
        return False
    if _main_strategy_rotation_recovery_strict():
        if notional_usd + 1e-9 < _recovery_rotation_min_notional_usd():
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
    cycles_since_exit: int | None = None,
) -> None:
    """TEMPORARY (48-hour sprint): structured P2 relief decision log for ops triage."""
    wm_s = "n/a" if wm_equiv_usd is None else f"${wm_equiv_usd:.2f}"
    notional_s = "n/a" if notional_usd is None else f"${notional_usd:.2f}"
    signal_s = "n/a" if signal_strength is None else f"{signal_strength:.2f}"
    tier_s = (
        "n/a"
        if wm_equiv_usd is None
        else _profit_take_stack_tier(float(wm_equiv_usd))
    )
    line = (
        f"{_PROFIT_TAKE_P2_RELIEF_CHECK_LOG} | wm={wm_s} | stack_tier={tier_s} | "
        f"notional={notional_s} | signal={signal_s} | allowed={allowed}"
    )
    if cycles_since_exit is not None:
        line += f" | cycles_since_exit={cycles_since_exit}"
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
    After tiered idle cycles without a WMATIC→stable exit, stack/notional meet tiered force
    floors (healthy **≥ $8**, low/moderate **≥ $10**; long-idle low stack **≥ $1.35**) and
    force-allow a sub-``MIN_TRADE_USD`` take — bypassing standard P2 wm/notional/signal gates.
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
        profit_signal=profit_signal,
        balances=balances,
    )
    strength = _profit_take_balance_relief_signal_strength(
        decision,
        profit_signal,
        wmatic_usd_equiv=wm_equiv_usd,
    )
    allowed = True
    reason: str | None = None
    if _main_strategy_mild_loss_rotation_min_notional_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=current_price_usd,
        min_trade_usd=min_trade_usd,
        profit_signal=profit_signal,
        state=state,
    ):
        _log_profit_take_p2_relief_check(
            wm_equiv_usd=wm_equiv_usd,
            notional_usd=notional_usd,
            signal_strength=strength,
            allowed=True,
            floor_usd=float(_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD),
            reason="mild_loss_idle_rotation_bypass",
            cycles_since_exit=cycles_since_exit,
        )
        return True
    if notional_usd + 1e-9 >= eff_min:
        allowed = False
        reason = "notional_at_or_above_min_trade"
    elif force_small:
        stack_label = _profit_take_stack_tier(wm_equiv_usd) + "_stack"
        if _profit_take_long_idle_active(wm_equiv_usd, cycles_since_exit):
            stack_label += "+long_idle"
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
        cycles_since_exit=cycles_since_exit,
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
    wm_equiv_for_fast = float(balances.wmatic) * float(current_price_usd)
    mild_loss_recovery_p2 = _main_strategy_mild_loss_recovery_overrides_x_signal_p2_defer(
        profit_signal,
        wm_equiv_for_fast,
        balances=balances,
        state=state,
    )
    low_stables_rebuild = _main_strategy_low_stables_dust_rebuild_eligible(
        decision,
        balances=balances,
        current_price_usd=current_price_usd,
    )
    if (
        _signal_driven_rotation_x_signal_first()
        and not mild_loss_recovery_p2
        and not low_stables_rebuild
    ):
        print(
            f"{runtime._nanolog()}Signal-Driven Rotation: P2 WMATIC→stable deferred — "
            "strong X-Signal BUY has cycle priority"
        )
        return False
    direction = str(decision.direction or "").strip().upper()
    if direction not in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        return False
    if _main_strategy_mild_loss_rotation_min_notional_bypass_allowed(
        decision,
        balances=balances,
        current_price_usd=current_price_usd,
        min_trade_usd=min_trade_usd,
        profit_signal=profit_signal,
        state=state,
    ):
        notional_usd = _decision_notional_usd(decision, current_price_usd=current_price_usd)
        _log_mild_loss_recovery_min_notional_bypass(
            wm_equiv_usd=float(balances.wmatic) * float(current_price_usd),
            notional_usd=float(notional_usd or 0.0),
            min_trade_usd=min_trade_usd,
            profit_signal=profit_signal,
            state=state,
            path="p2_override",
        )
        return True
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
    """Stack base min_out buffer with high-conviction add-on (|signal| ≥ 0.85)."""
    if signal_strength is None:
        return 0
    s = abs(float(signal_strength))
    if s + 1e-9 >= _X_SIGNAL_VERY_STRONG_STRENGTH:
        return int(cfg.X_SIGNAL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS)
    if s + 1e-9 >= _X_SIGNAL_HIGH_CONVICTION_STRENGTH:
        return max(0, int(cfg.X_SIGNAL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS) // 2)
    return 0


def _x_signal_stf_sort_penalty(state: dict | None, symbol: str) -> int:
    """CRITICAL: deprioritize assets in STF backoff so rotation tries healthier symbols first.

    Higher penalty = sort later. Escalates with short cooldown, long pause, and repeat pause cycles.
    """
    sym = str(symbol).strip().upper()
    if not state or not sym:
        return 0
    root = state.get(_X_SIGNAL_STF_STATE_KEY) or {}
    entry = root.get(sym) or {}
    paused, _ = _x_signal_stf_pause_active(state, sym)
    failures = int(entry.get("failures") or 0)
    pause_gen = int(entry.get("pause_generations") or 0)
    if paused:
        if pause_gen >= 2:
            return 4
        if pause_gen >= 1:
            return 3
        return 2 if failures > 0 else 1
    if failures >= 1:
        return 1
    return 0


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


def _is_loss_cut_executable_decision(decision: TradeDecision | None) -> bool:
    if decision is None or not decision.should_execute:
        return False
    if str(decision.direction or "").strip().upper() != "EQUITY_TO_USDC":
        return False
    return "loss-cut" in str(decision.message or "").lower()


def _reserve_loss_cut_cooldown_before_swap(decision: TradeDecision) -> None:
    """Persist per-asset cooldown as soon as loss-cut is selected (before long approve/swap)."""
    asset = getattr(decision, "cooldown_asset", None)
    if not isinstance(asset, tuple) or len(asset) < 2:
        return
    sym_ca, secs_a = str(asset[0] or "").strip(), int(asset[1])
    if sym_ca and secs_a > 0:
        cs = _facade()
        cs.mark_asset_traded(sym_ca, cooldown_seconds=secs_a)


def _x_signal_stf_pause_entry(state: dict | None, symbol: str) -> dict:
    if state is None:
        raise ValueError("state is required for X-SIGNAL STF backoff tracking")
    root = state.setdefault(_X_SIGNAL_STF_STATE_KEY, {})
    return root.setdefault(
        str(symbol).strip().upper(),
        {"failures": 0, "paused_until": 0.0, "pause_generations": 0},
    )


def _x_signal_stf_pause_active(state: dict | None, symbol: str) -> tuple[bool, str]:
    """True when repeated STF failures triggered a temporary pause for this asset."""
    if not state or not symbol:
        return False, ""
    entry = _x_signal_stf_pause_entry(state, symbol)
    until = float(entry.get("paused_until") or 0.0)
    now = time.time()
    if until > now:
        remain = int(until - now)
        pause_gen = int(entry.get("pause_generations") or 0)
        return (
            True,
            f"stf_pause_active ({remain}s remaining, failures={int(entry.get('failures') or 0)}, "
            f"pause_gen={pause_gen})",
        )
    if until > 0 and until <= now:
        entry["paused_until"] = 0.0
    return False, ""


def _record_x_signal_stf_failure(state: dict, decision: TradeDecision, swap_outcome: dict | None) -> None:
    """CRITICAL: per-asset STF backoff — short cooldown each revert; long pause after threshold."""
    if not swap_outcome or not bool(swap_outcome.get("stf")):
        return
    sym = _x_signal_symbol_from_decision(decision)
    entry = _x_signal_stf_pause_entry(state, sym)
    entry["failures"] = int(entry.get("failures") or 0) + 1
    threshold = max(1, int(cfg.X_SIGNAL_STF_PAUSE_AFTER_FAILURES))
    short_cd = max(60, int(cfg.X_SIGNAL_STF_FAILURE_COOLDOWN_SECONDS))
    long_pause_secs = max(60, int(cfg.X_SIGNAL_STF_PAUSE_SECONDS))
    failures = int(entry["failures"])
    print(
        f"{_X_SIGNAL_STF_LOG} | STF failure recorded | sym={sym} | "
        f"failures={failures}/{threshold} | slippage_bps={swap_outcome.get('slippage_bps')} | "
        f"min_out={swap_outcome.get('amount_out_min')} | fee_tier={swap_outcome.get('fee_tier')} | "
        f"revert={str(swap_outcome.get('revert_reason') or '')[:120]}"
    )
    if failures >= threshold:
        pause_gen = int(entry.get("pause_generations") or 0) + 1
        entry["pause_generations"] = pause_gen
        mult = max(1.0, float(cfg.X_SIGNAL_STF_PAUSE_ESCALATION_MULTIPLIER))
        escalated = int(long_pause_secs * (mult ** (pause_gen - 1)))
        max_pause = max(60, int(cfg.X_SIGNAL_STF_MAX_PAUSE_SECONDS))
        pause_secs = min(max(60, escalated), max_pause)
        entry["paused_until"] = time.time() + float(pause_secs)
        entry["failures"] = 0
        print(
            f"{_X_SIGNAL_STF_LOG} | pausing X-SIGNAL BUY for {sym} | "
            f"duration={pause_secs}s | pause_generation={pause_gen} | "
            f"base={long_pause_secs}s | multiplier={mult} | reason=repeated_stf_escalated"
        )
    else:
        until = time.time() + float(short_cd)
        entry["paused_until"] = max(float(entry.get("paused_until") or 0.0), until)
        print(
            f"{_X_SIGNAL_STF_LOG} | STF cooldown for {sym} | "
            f"duration={short_cd}s | failures={failures}/{threshold}"
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


def _x_signal_apply_blocked_symbol_filter(
    decision: TradeDecision | None,
    *,
    log_skip: Callable[[str], None] | None = None,
) -> TradeDecision | None:
    """Block-list gate for X-SIGNAL USDC→equity (decision + fallback router execution)."""
    if not _is_x_signal_usdc_equity_buy(decision):
        return decision
    sym = _x_signal_symbol_from_decision(decision)
    if not signal_module.is_xsignal_symbol_blocked(sym):
        return decision
    _, source = signal_module.load_xsignal_blocked_symbols()
    signal_module.log_xsignal_blocked_skip(sym, source=source)
    if log_skip is not None:
        log_skip(f"xsignal_blocked_symbol ({sym})")
    return None


def _x_signal_small_high_conviction_min_strength(
    decision_notional_usd: float | None,
) -> float:
    """Minimum |signal| for small-tier fallback (looser for ~$10 gated trades and recovery)."""
    base = float(_X_SIGNAL_HIGH_CONVICTION_STRENGTH)
    small_max = float(getattr(cfg, "X_SIGNAL_SMALL_GATED_MAX_NOTIONAL_USD", 12.0))
    small_min = float(getattr(cfg, "X_SIGNAL_SMALL_GATED_MIN_STRENGTH", 0.80))
    if (
        decision_notional_usd is not None
        and float(decision_notional_usd) + 1e-9 <= small_max
        and small_min + 1e-9 < base
    ):
        return min(base, small_min)
    if _x_signal_recovery_gate_relaxation_active():
        return float(_X_SIGNAL_VERY_STRONG_STRENGTH) - 0.10
    return base


def _x_signal_small_high_conviction_relaxed_slippage(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> tuple[int, int] | None:
    """High fallback slippage for small USDC→equity X-SIGNAL (>=0.85, or >=0.80 at <=$12 notional)."""
    if str(decision.direction or "").strip().upper() != "USDC_TO_EQUITY":
        return None
    strength = decision.signal_strength
    if strength is None or float(strength) <= 0:
        return None
    min_strength = _x_signal_small_high_conviction_min_strength(decision_notional_usd)
    if abs(float(strength)) + 1e-9 < min_strength:
        return None
    if decision_notional_usd is None:
        return None
    if decision_notional_usd + 1e-9 > float(
        getattr(cfg, "X_SIGNAL_SMALL_GATED_MAX_NOTIONAL_USD", _X_SIGNAL_SMALL_HIGH_CONVICTION_MAX_NOTIONAL_USD)
    ):
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


def _x_signal_conservative_primary_bps(primary_bps: int, signal_strength: float | None) -> int:
    """CRITICAL: |signal|>=0.90 uses a slightly lower first ramp step; retry ramp still reaches tier max."""
    if signal_strength is None or abs(float(signal_strength)) + 1e-9 < _X_SIGNAL_VERY_STRONG_STRENGTH:
        return int(primary_bps)
    relief = max(0, int(cfg.X_SIGNAL_HIGH_CONVICTION_PRIMARY_RELIEF_BPS))
    floor = 600
    return max(floor, int(primary_bps) - relief)


def _x_signal_default_relaxed_slippage(
    decision: TradeDecision,
) -> tuple[int, int, int]:
    """CRITICAL: fallback tier for USDC→equity X-SIGNAL without gated/small enhanced params."""
    strength = decision.signal_strength
    min_out = int(cfg.X_SIGNAL_DEFAULT_MIN_OUT_EXTRA_BPS) + _x_signal_min_out_extra_bps(strength)
    primary = _x_signal_conservative_primary_bps(int(cfg.X_SIGNAL_DEFAULT_FALLBACK_PRIMARY_BPS), strength)
    return (
        primary,
        int(cfg.X_SIGNAL_DEFAULT_FALLBACK_RETRY_BPS),
        min_out,
    )


def _resolve_x_signal_enhanced_fallback_execution(
    decision: TradeDecision,
    *,
    decision_notional_usd: float | None,
) -> tuple[int, int, int | None] | None:
    """CRITICAL: (primary_bps, retry_bps, min_out_extra_bps) for X-SIGNAL fallback router execution.

    Signal-driven rotation only pays off when selected BUYs fill on-chain; every USDC→equity X-SIGNAL
    path uses enhanced slippage ramp + min_out buffer (small → gated → default).
    """
    if not _is_x_signal_usdc_equity_buy(decision):
        return None
    strength = decision.signal_strength
    small = _x_signal_small_high_conviction_relaxed_slippage(
        decision,
        decision_notional_usd=decision_notional_usd,
    )
    if small is not None:
        min_out = int(cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS) + _x_signal_min_out_extra_bps(
            strength
        )
        primary = _x_signal_conservative_primary_bps(small[0], strength)
        return primary, small[1], min_out
    gated = _x_signal_gated_trade_relaxed_slippage(
        decision,
        decision_notional_usd=decision_notional_usd,
    )
    if gated is not None:
        min_out = int(cfg.X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS) + _x_signal_min_out_extra_bps(strength)
        primary = _x_signal_conservative_primary_bps(gated[0], strength)
        return primary, gated[1], min_out
    return _x_signal_default_relaxed_slippage(decision)


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
    operator_paused = bool(ctrl.paused)
    reserve_ctx = _operating_reserve_buy_block_context(balances)
    entries_paused = operator_paused or reserve_ctx is not None
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
    if operator_paused:
        print("[CONTROL] paused=True → skipping new entry trades (protection exits still allowed)")
    elif reserve_ctx is not None:
        _log_operating_reserve_defer(
            stable_usd=float(reserve_ctx["stable_usd"]),
            reserve_floor_usd=float(reserve_ctx["reserve_floor_usd"]),
            seed_usd=float(reserve_ctx["seed_usd"]),
        )
    # ``ctrl.force_defensive`` is parsed in ``load_cycle_control`` for future wiring — does not alter protection yet.

    # TEMPORARY (May 2026 sprint): track cycles since last WMATIC→stable profit exit for force-relief.
    _profit_take_bump_cycle_counter(state)
    _low_stables_dust_rebuild_bump_cycle(state)
    _low_stables_dust_rebuild_reconcile_state(state)

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
    wmatic_usd_cycle = float(balances.wmatic) * float(current_price)
    x_signal_rotation_first = _signal_driven_rotation_x_signal_first()
    x_signal_rotation_first = _apply_low_stables_rebuild_rotation_precedence(
        x_signal_rotation_first,
        balances=balances,
        state=state,
        wmatic_usd=wmatic_usd_cycle,
    )
    print(
        "🔍 DECISION PATH | precedence: PROTECTION → HIGH_RISK_LOSS_CUT → "
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

    loss_cut_decision = signal_module.try_high_risk_loss_cut_equity_decision(
        balances,
        dry_run=dry_run,
        state=state,
    )
    if loss_cut_decision is not None and loss_cut_decision.should_execute:
        lc_dir = str(loss_cut_decision.direction or "").strip().upper()
        if pause_active and lc_dir == "EQUITY_TO_USDC":
            if "loss-cut" in str(loss_cut_decision.message or "").lower():
                print(
                    f"{runtime._nanolog()}defensive_pause: loss-cut SELL allowed "
                    f"({_x_signal_symbol_from_decision(loss_cut_decision)} underwater)"
                )
            else:
                cs._log_trade_skipped(
                    f"defensive_pause (risk=HIGH, remaining_cycles={pause_remaining}) — pausing equity SELL"
                )
                loss_cut_decision = None
        if loss_cut_decision is not None and entries_paused and lc_dir in _CONTROL_PAUSE_BLOCK_ENTRIES:
            cs._log_trade_skipped("control.json paused=True — skipping loss-cut entry trade")
            loss_cut_decision = None
        if loss_cut_decision is not None:
            loss_cut_decision = _x_signal_apply_stf_pause_filter(loss_cut_decision, state=state)
        if loss_cut_decision is not None:
            loss_cut_decision = _x_signal_apply_blocked_symbol_filter(
                loss_cut_decision,
                log_skip=cs._log_trade_skipped,
            )
        if loss_cut_decision is not None and loss_cut_decision.should_execute:
            print("🔍 DECISION PATH: HIGH_RISK_LOSS_CUT (underwater X-SIGNAL equity trim)")
            x_dust_min_lc = _x_signal_equity_effective_dust_min(balances)
            lc_notional = _decision_notional_usd(loss_cut_decision, current_price_usd=current_price)
            blocked_lc, edge_lc = _decision_blocked_by_min_net_edge(
                loss_cut_decision,
                trade_usd=lc_notional,
                gas_gwei=planning_gas_gwei,
                log_skip=cs._log_trade_skipped,
                stage="loss_cut_decision",
            )
            if blocked_lc:
                decision_log.log_x_signal_decision(
                    _x_signal_symbol_from_decision(loss_cut_decision),
                    "REJECT",
                    "below_min_net_edge",
                    signal=loss_cut_decision.signal_strength,
                    expected_edge_pct=edge_lc,
                    notional_usd=lc_notional,
                    wmatic_balance=float(balances.wmatic),
                    extra=f"floor={_min_net_edge_floor_pct():.2f}%",
                    state=state,
                )
            elif not _defer_if_dust(
                loss_cut_decision,
                branch_name="HIGH_RISK_LOSS_CUT",
                current_price_usd=current_price,
                min_trade_usd=x_dust_min_lc,
            ):
                decision_log.record_x_signal_cycle_outcome(
                    state,
                    taken=True,
                    reason="loss_cut_executable",
                    wmatic_balance=float(balances.wmatic),
                )
                return loss_cut_decision

    fe_runway_decision = signal_module.try_fe_stable_runway_trim_equity_decision(
        balances,
        dry_run=dry_run,
        state=state,
        wmatic_usd=wmatic_usd_cycle,
    )
    if fe_runway_decision is not None and fe_runway_decision.should_execute:
        fe_notional = _decision_notional_usd(fe_runway_decision, current_price_usd=current_price)
        x_dust_min_fe = _x_signal_equity_effective_dust_min(balances)
        blocked_fe, edge_fe = _decision_blocked_by_min_net_edge(
            fe_runway_decision,
            trade_usd=fe_notional,
            gas_gwei=planning_gas_gwei,
            log_skip=cs._log_trade_skipped,
            stage="fe_stable_runway_trim",
        )
        if blocked_fe:
            decision_log.log_x_signal_decision(
                _x_signal_symbol_from_decision(fe_runway_decision),
                "REJECT",
                "below_min_net_edge",
                notional_usd=fe_notional,
                expected_edge_pct=edge_fe,
                wmatic_balance=float(balances.wmatic),
                extra=f"floor={_min_net_edge_floor_pct():.2f}%",
                state=state,
            )
        elif not _defer_if_dust(
            fe_runway_decision,
            branch_name="FE_STABLE_RUNWAY",
            current_price_usd=current_price,
            min_trade_usd=x_dust_min_fe,
        ):
            print("🔍 DECISION PATH: FE_STABLE_RUNWAY (EQUITY→USDC trim for stable buffer)")
            decision_log.record_x_signal_cycle_outcome(
                state,
                taken=True,
                reason="fe_stable_runway_trim",
                wmatic_balance=float(balances.wmatic),
            )
            return fe_runway_decision

    def _resolve_x_signal_equity_decision() -> Optional[TradeDecision]:
        if not cs.ENABLE_X_SIGNAL_EQUITY:
            return None
        xd_local = cs_try_x_signal_equity_decision(balances, dry_run=dry_run, state=state)
        if (
            pause_active
            and xd_local
            and xd_local.should_execute
        ):
            xd_dir_pause = str(xd_local.direction or "").strip().upper()
            if xd_dir_pause == "EQUITY_TO_USDC":
                msg_lc = str(xd_local.message or "").lower()
                if "loss-cut" in msg_lc:
                    print(
                        f"{runtime._nanolog()}defensive_pause: loss-cut SELL allowed "
                        f"({_x_signal_symbol_from_decision(xd_local)} underwater)"
                    )
            elif xd_dir_pause in {"USDC_TO_EQUITY"}:
                strength = float(xd_local.signal_strength or 0.0)
                if (
                    risk_level == "HIGH"
                    and signal_module.reduced_high_risk_xsignal_eligible(
                        total_portfolio_usd=float(balances.total_portfolio_usd),
                        signal_strength=strength,
                    )
                ):
                    _clear_defensive_pause_window(state)
                    print(
                        f"{runtime._nanolog()}defensive_pause skipped for reduced HIGH-risk X-SIGNAL "
                        f"(signal={strength:.2f}, total_portfolio_usd=${float(balances.total_portfolio_usd):.2f})"
                    )
                else:
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
            xd_local = _x_signal_apply_blocked_symbol_filter(xd_local, log_skip=cs._log_trade_skipped)
        if xd_local and xd_local.should_execute:
            print("🔍 DECISION PATH: X_SIGNAL_EQUITY")
            x_dust_min = _x_signal_equity_effective_dust_min(balances)
            x_notional = _decision_notional_usd(xd_local, current_price_usd=current_price)
            blocked_x, edge_x = _decision_blocked_by_min_net_edge(
                xd_local,
                trade_usd=x_notional,
                gas_gwei=planning_gas_gwei,
                log_skip=cs._log_trade_skipped,
                stage="x_signal_decision",
            )
            if blocked_x:
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
                if not _main_strategy_mild_loss_rotation_min_notional_bypass_allowed(
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
        # May 2026: rotate small WMATIC→stable on mild loss before copy/main accumulate paths.
        wm_hold_usd = float(balances.wmatic) * float(current_price)
        hold_fast_rotation = _main_strategy_mild_loss_fast_rotation_eligible(
            profit_signal,
            wm_hold_usd,
            float(balances.wmatic),
            balances,
        )
        hold_mild_loss_idle = _main_strategy_mild_loss_idle_context(
            profit_signal,
            wm_hold_usd,
            _profit_take_cycles_since_exit(state),
            balances=balances,
            wmatic_qty=float(balances.wmatic),
        )
        if (
            not _signal_driven_rotation_x_signal_first()
            or hold_fast_rotation
            or hold_mild_loss_idle
        ):
            hold_idle = _main_strategy_idle_rotation_sell_decision(
                balances,
                current_price,
                state=state,
                profit_signal=profit_signal,
            )
            if hold_idle is not None and hold_idle.should_execute:
                eff_pt_min = float(getattr(cs, "MIN_TRADE_USD", 0.0) or 0.0)
                if _wmatic_stable_p2_relief_override_active(
                    hold_idle,
                    balances=balances,
                    current_price_usd=current_price,
                    min_trade_usd=eff_pt_min,
                    profit_signal=profit_signal,
                    state=state,
                ):
                    if not _main_strategy_mild_loss_rotation_min_notional_bypass_allowed(
                        hold_idle,
                        balances=balances,
                        current_price_usd=current_price,
                        min_trade_usd=eff_pt_min,
                        profit_signal=profit_signal,
                        state=state,
                    ):
                        print(_PROFIT_TAKE_P2_RELIEF_LOG)
                    decision_log.log_tracking_summary(state)
                    return hold_idle
                # Execution-time P2 still needs HOLD gain_pct; return decision for min_trade_guard path.
                decision_log.log_tracking_summary(state)
                return hold_idle

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
            blocked_fb, edge_fb = _decision_blocked_by_min_net_edge(
                fallback_xd,
                trade_usd=fb_notional,
                gas_gwei=planning_gas_gwei,
                log_skip=cs._log_trade_skipped,
                stage="stable_rotation_fallback",
            )
            if blocked_fb:
                decision_log.log_main_strategy_decision(
                    action="REJECT",
                    reason="below_min_net_edge",
                    wmatic_balance=float(balances.wmatic),
                    wmatic_usd=float(balances.wmatic) * float(current_price),
                    extra=(
                        f"stable_rotation_fallback notional=${fb_notional} "
                        f"expected_net_return_pct={edge_fb:.2f}% floor={_min_net_edge_floor_pct():.2f}%"
                    ),
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
    main_decision = select_main_strategy_trade(
        balances,
        current_price,
        state=state,
        profit_signal=profit_signal,
    )
    _log_main_strategy_outcome(main_decision)
    main_dir = str(main_decision.direction or "").strip().upper()
    eff_main_min_usd = float(getattr(cs, "MIN_TRADE_USD", 0.0) or 0.0)
    main_dust_min_usd = eff_main_min_usd
    if main_dir in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        if _main_strategy_mild_loss_rotation_min_notional_bypass_allowed(
            main_decision,
            balances=balances,
            current_price_usd=current_price,
            min_trade_usd=eff_main_min_usd,
            profit_signal=profit_signal,
            state=state,
        ):
            main_dust_min_usd = float(_MAIN_STRATEGY_MILD_LOSS_IDLE_NOTIONAL_FLOOR_USD)
        if _main_strategy_low_stables_dust_rebuild_override_active(
            main_decision,
            balances=balances,
            current_price_usd=current_price,
            state=state,
        ):
            notional_rb = _decision_notional_usd(main_decision, current_price_usd=current_price)
            notional_s = f"{notional_rb:.2f}" if notional_rb is not None else "?"
            stable_usd = float(balances.usdt) + float(balances.usdc)
            print(
                f"{_MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_LOG} | "
                f"direction={main_dir} | notional=${notional_s} | stables=${stable_usd:.2f} | "
                f"wmatic_usd=${float(balances.wmatic) * float(current_price):.2f} | "
                f"bypassing dust defer (floor=${float(_MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD):.2f})"
            )
            _record_low_stables_dust_rebuild_pending(state)
            return main_decision
        # TEMPORARY SPRINT FIX - May 2026: P2 bypass-first — overrides MAIN_STRATEGY dust defer / $10 floor.
        if _wmatic_stable_p2_relief_override_active(
            main_decision,
            balances=balances,
            current_price_usd=current_price,
            min_trade_usd=eff_main_min_usd,
            profit_signal=profit_signal,
            state=state,
        ):
            if main_dust_min_usd >= eff_main_min_usd:
                print(_PROFIT_TAKE_P2_RELIEF_LOG)
            return main_decision
        if main_dust_min_usd >= eff_main_min_usd:
            main_dust_min_usd = float(_MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD)
    main_msg_l = str(main_decision.message or "").lower()
    main_entry_blocked = (
        main_dir in _CONTROL_PAUSE_BLOCK_ENTRIES
        or (
            not main_dir
            and (
                "main wmatic buy deferred" in main_msg_l
                or "buying wmatic" in main_msg_l
            )
        )
    )
    if entries_paused and main_entry_blocked:
        cs._log_trade_skipped("control.json paused=True — skipping main-strategy entry trade")
        return TradeDecision(message="ℹ️ Paused via control.json (no new entries this cycle)")
    if main_decision.should_execute and main_dir == "USDT_TO_WMATIC":
        main_notional = _decision_notional_usd(main_decision, current_price_usd=current_price)
        blocked_main, _edge_main = _decision_blocked_by_min_net_edge(
            main_decision,
            trade_usd=main_notional,
            gas_gwei=planning_gas_gwei,
            log_skip=cs._log_trade_skipped,
            stage="main_strategy_decision",
        )
        if blocked_main:
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
        min_trade_usd=main_dust_min_usd if main_dust_min_usd < eff_main_min_usd else None,
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
    print(
        f"{runtime._nanolog()}X_SIGNAL_HONOR_FULL_BLOCKLIST="
        f"{bool(getattr(cfg, 'X_SIGNAL_HONOR_FULL_BLOCKLIST', False))} | "
        f"FE_STABLE_RUNWAY_ENABLED={bool(getattr(cfg, 'FE_STABLE_RUNWAY_ENABLED', True))}"
    )
    _log_min_net_edge_policy_once(stage="execution")
    state = cs.load_state()
    balances = cs.get_balances()
    print(f"{runtime._nanolog()}WALLET BALANCE | USDC=${balances.usdc:.2f} | Address={cs.WALLET}")
    _stable = float(balances.usdt) + float(balances.usdc)
    # Cleanup #1 (May 2026): emit TOTAL via the canonical helper so the log line,
    # portfolio_history.csv writer, and scripts/pnl_report.py all read the same float.
    _total_usd = runtime.compute_authoritative_total_usd(balances)
    print(
        f"{runtime._nanolog()}WALLET TOTAL USD | TOTAL=${_total_usd:.2f} "
        f"| USDT=${balances.usdt:.2f} | USDC=${balances.usdc:.2f} | STABLE_USD=${_stable:.2f} "
        f"| WMATIC={balances.wmatic:.6f} "
        f"| POL={balances.pol:.6f} | POL_USD=${balances.pol_usd:.2f} "
        f"| FE_USD=${balances.followed_equity_usd:.2f}"
    )
    print(
        f"Real USDT: {balances.usdt:.2f} | USDC: {balances.usdc:.2f} | "
        f"WMATIC: {balances.wmatic:.2f} | POL: {balances.pol:.2f}"
    )

    if not dry_run and cs.AUTO_TOPUP_POL:
        await asyncio.to_thread(
            cs.maybe_auto_topup_pol,
            float(cs.MIN_POL_FOR_GAS),
            context="cycle_start",
            min_gas_units=int(getattr(cs, "POL_EXECUTION_GAS_UNITS", 600_000)),
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
        if _is_loss_cut_executable_decision(decision):
            _reserve_loss_cut_cooldown_before_swap(decision)
        cs.save_state(state)

        if decision.message:
            print(decision.message)

        if not decision.should_execute:
            cs._log_trade_skipped("protection/strategy returned no actionable trade")
            print("ℹ️ No actionable trade this cycle")
            return

        decision = _x_signal_apply_blocked_symbol_filter(decision, log_skip=cs._log_trade_skipped)
        if decision is None or not decision.should_execute:
            print("ℹ️ No actionable trade this cycle (X-SIGNAL symbol block list)")
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
                # Keep HOLD payload for mild-loss idle rotation at execution (was cleared → P2 always failed).
                if (
                    not should_tp
                    and profit_signal_guard is not None
                    and str(profit_signal_guard.get("reason") or "").strip().upper() != "HOLD"
                ):
                    profit_signal_guard = None
            if _x_signal_min_trade_guard_bypass(
                decision,
                decision_notional_usd=decision_notional_usd,
                min_trade_usd=min_trade_usd,
            ):
                print("[nanoclaw-av] X-SIGNAL min_trade_guard bypassed (high conviction)")
            elif _main_strategy_mild_loss_rotation_min_notional_bypass_allowed(
                decision,
                balances=balances,
                current_price_usd=current_price,
                min_trade_usd=min_trade_usd,
                profit_signal=profit_signal_guard,
                state=state,
            ):
                _log_mild_loss_recovery_min_notional_bypass(
                    wm_equiv_usd=float(balances.wmatic) * float(current_price),
                    notional_usd=float(decision_notional_usd),
                    min_trade_usd=min_trade_usd,
                    profit_signal=profit_signal_guard,
                    state=state,
                    path="execution",
                )
            elif _profit_take_balance_relief_bypass_allowed(
                decision,
                balances=balances,
                current_price_usd=current_price,
                min_trade_usd=min_trade_usd,
                profit_signal=profit_signal_guard,
                state=state,
            ):
                print(_PROFIT_TAKE_P2_RELIEF_LOG)
            elif _main_strategy_low_stables_dust_rebuild_execution_bypass(
                state,
                decision,
                decision_notional_usd=decision_notional_usd,
                min_trade_usd=min_trade_usd,
            ):
                print(
                    f"{runtime._nanolog()}{_MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_LOG} | "
                    f"min_trade_guard bypassed (${decision_notional_usd:.2f} < MIN_TRADE_USD ${min_trade_usd:.2f})"
                )
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
        pol_target = float(
            runtime._pol_target_for_trade(
                float(cs.MIN_POL_FOR_GAS),
                urgent=True,
                gas_units=int(getattr(cs, "POL_EXECUTION_GAS_UNITS", 600_000)),
            )
        )
        if pol_now < pol_target:
            if cs.AUTO_TOPUP_POL:
                topup_ok = await asyncio.to_thread(
                    cs.maybe_auto_topup_pol,
                    float(cs.MIN_POL_FOR_GAS),
                    context="pre_trade",
                    force=True,
                    min_gas_units=int(getattr(cs, "POL_EXECUTION_GAS_UNITS", 600_000)),
                )
                pol_now = float(cs.get_pol_balance())
                if not topup_ok or pol_now < pol_target:
                    cs._log_trade_skipped(f"POL low (auto top-up failed; need {pol_target:.4f})")
                    print(
                        f"{runtime._nanolog()}AUTO-POL failed — trade blocked "
                        f"(pol≈{pol_now:.4f} < target≈{pol_target:.4f})"
                    )
                    return
            else:
                cs._log_trade_skipped(f"POL low (have {pol_now:.4f}, need {pol_target:.4f})")
                print(
                    f"{runtime._nanolog()}POL low (pol≈{pol_now:.4f} < {pol_target:.4f}) "
                    "and AUTO_TOPUP_POL=false — trade blocked"
                )
                return

        if _is_loss_cut_executable_decision(decision):
            from modules import x_signal_position as xsp

            if not xsp.allow_high_risk_loss_cut_xsignal():
                cs._log_trade_skipped(
                    "loss-cut disabled at execution (ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false)"
                )
                print(
                    f"{runtime._nanolog()}loss-cut blocked at execution — "
                    "ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false"
                )
                return
            min_loss_cut_usd = float(
                getattr(cfg, "HIGH_RISK_LOSS_CUT_MIN_EQUITY_USD", getattr(cfg, "MIN_TRADE_USD", 10.0))
                or 0.0
            )
            if (
                min_loss_cut_usd > 0
                and decision_notional_usd is not None
                and float(decision_notional_usd) + 1e-9 < min_loss_cut_usd
            ):
                cs._log_trade_skipped(
                    f"loss-cut dust at execution (${float(decision_notional_usd):.2f} < ${min_loss_cut_usd:.2f})"
                )
                print(
                    f"{runtime._nanolog()}loss-cut skipped — dust "
                    f"(notional=${float(decision_notional_usd):.2f})"
                )
                return

        gas_status = cs.get_gas_status(urgent=True, min_pol=pol_target)
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
        if is_x_signal_buy and x_signal_exec is not None:
            fallback_slip_bps, fallback_slip_retry_bps, fallback_min_out_extra_bps = x_signal_exec
            mo_extra = int(fallback_min_out_extra_bps or 0)
            gated_mo = int(cfg.X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS)
            small_mo = int(cfg.X_SIGNAL_SMALL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS)
            if mo_extra >= gated_mo + small_mo:
                tier = "gated+high_conviction"
            elif mo_extra >= gated_mo:
                tier = "gated"
            elif mo_extra >= small_mo:
                tier = "small_high_conviction"
            else:
                tier = "default"
            ramp = _x_signal_fallback_slippage_ramp(fallback_slip_bps, fallback_slip_retry_bps)
            print(
                f"{_X_SIGNAL_STF_LOG} | EXEC ATTEMPT | sym={x_sym} | tier={tier} | "
                f"notional=${decision_notional_usd:.2f} | signal={decision.signal_strength} | "
                f"fallback_slip={fallback_slip_bps}/{fallback_slip_retry_bps} bps | "
                f"slippage_ramp={'→'.join(str(b) for b in ramp)} | "
                f"min_out_extra={mo_extra} bps | quote=v3_stable_prefer+quoter_v2+v2_fallback"
            )

        runtime.touch_lock()
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
                from modules import x_signal_position as xsp

                pending_root = state.setdefault("x_signal_pending_entries", {})
                pending = pending_root.pop(x_sym, None) if x_sym else None
                entry_px = float((pending or {}).get("entry_price_usd", 0.0) or 0.0)
                if entry_px <= 0:
                    entry_px = float(decision.trade_size or 0.0) / max(
                        float(decision.trade_size or 1.0), 1.0
                    )
                xsp.record_equity_entry(
                    state,
                    x_sym,
                    entry_price_usd=entry_px,
                    notional_usd=float(decision.trade_size or 0.0),
                    tx_hash=str(tx_hash),
                )
            elif (
                str(decision.direction or "").strip().upper() == "EQUITY_TO_USDC"
                and "loss-cut" in str(decision.message or "").lower()
            ):
                print(
                    f"{runtime._nanolog()}HIGH risk loss-cut executed | "
                    f"sym={_x_signal_symbol_from_decision(decision)} | tx={tx_hash}"
                )
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
                if bool(_low_stables_dust_rebuild_state(state).get("pending_execution")):
                    _record_low_stables_dust_rebuild_executed(state)
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
                slip_used = swap_outcome.get("slippage_bps")
                min_out_used = swap_outcome.get("amount_out_min")
                fee_used = swap_outcome.get("fee_tier")
                mo_extra_used = swap_outcome.get("min_out_extra_bps")
                print(
                    f"{_X_SIGNAL_STF_LOG} | EXEC FAILED | sym={x_sym} | stf={stf_flag} | "
                    f"notional=${float(decision_notional_usd or 0):.2f} | signal={decision.signal_strength} | "
                    f"slippage_bps={slip_used} | min_out={min_out_used} | "
                    f"min_out_extra_bps={mo_extra_used} | fee_tier={fee_used} | "
                    f"amount_in={decision.amount_in} | "
                    f"revert={str(swap_outcome.get('revert_reason') or 'unknown')[:200]}"
                )
            if str(decision.direction or "").strip().upper() in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
                decision_log.record_profit_take_execution(state, success=False, reason="swap_failed")
            print(f"{runtime._nanolog()}Swap failed — per-asset/per-wallet cooldown not applied")

        state["last_run"] = time.time()
        cs.save_state(state)
        print(f"✅ Cycle done — next in ~{cs.COOLDOWN_MINUTES} min")
    finally:
        cs.release_lock()


