"""Structured decision logging and basic counters for future learning/adaptation.

Pipe-delimited ``DECISION |`` lines are grep-friendly in ``real_cron.log`` and can be
aggregated offline. Counters persist in ``bot_state.json`` under ``decision_tracking``.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, MutableMapping, Optional

from . import runtime

logger = logging.getLogger(__name__)

# Persisted in bot_state.json — foundation for adaptive thresholds / policy tuning.
_TRACKING_KEY = "decision_tracking"

_BRANCH_X_SIGNAL = "X_SIGNAL"
_BRANCH_PROFIT_TAKE = "PROFIT_TAKE"
_BRANCH_MAIN_STRATEGY = "MAIN_STRATEGY"

_ACTION_ACCEPT = "ACCEPT"
_ACTION_REJECT = "REJECT"
_ACTION_TAKE = "TAKE"
_ACTION_HOLD = "HOLD"
_ACTION_DEFER = "DEFER"
_ACTION_EXECUTE = "EXECUTE"


def decision_tracking_state(state: dict | None) -> dict:
    """Return (and create) the ``decision_tracking`` bucket on bot state."""
    if state is None:
        return {}
    return state.setdefault(_TRACKING_KEY, {})


def _counter_bucket(state: dict | None, branch: str) -> MutableMapping[str, int]:
    root = decision_tracking_state(state)
    bucket = root.setdefault(branch, {})
    if not isinstance(bucket, dict):
        bucket = {}
        root[branch] = bucket
    return bucket  # type: ignore[return-value]


def bump_counter(state: dict | None, branch: str, field: str, *, delta: int = 1) -> int:
    """Increment a named counter; returns the new value."""
    bucket = _counter_bucket(state, branch)
    new_val = int(bucket.get(field, 0) or 0) + int(delta)
    bucket[field] = new_val
    return new_val


def _fmt_opt_float(value: float | None, *, digits: int = 3, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "n/a"


def _build_decision_line(
    *,
    branch: str,
    action: str,
    reason: str,
    symbol: str = "",
    signal_strength: float | None = None,
    expected_edge_pct: float | None = None,
    notional_usd: float | None = None,
    wmatic_balance: float | None = None,
    extra: str = "",
) -> str:
    sym = str(symbol).strip() or "n/a"
    act = str(action).strip().upper() or "UNKNOWN"
    rsn = str(reason).strip() or "unknown"
    parts = [
        "DECISION",
        f"branch={str(branch).strip().upper()}",
        f"action={act}",
        f"reason={rsn}",
        f"symbol={sym}",
        f"signal={_fmt_opt_float(signal_strength)}",
        f"edge_pct={_fmt_opt_float(expected_edge_pct, digits=2)}",
        f"notional_usd={_fmt_opt_float(notional_usd, digits=2)}",
        f"wmatic={_fmt_opt_float(wmatic_balance, digits=6)}",
    ]
    tail = str(extra).strip()
    if tail:
        parts.append(f"extra={tail}")
    return " | ".join(parts)


def log_decision(
    *,
    branch: str,
    action: str,
    reason: str,
    symbol: str = "",
    signal_strength: float | None = None,
    expected_edge_pct: float | None = None,
    notional_usd: float | None = None,
    wmatic_balance: float | None = None,
    extra: str = "",
    state: dict | None = None,
    counter_field: str | None = None,
) -> str:
    """Emit a standardized decision line via nanolog + logger.info; optionally bump a counter."""
    line = _build_decision_line(
        branch=branch,
        action=action,
        reason=reason,
        symbol=symbol,
        signal_strength=signal_strength,
        expected_edge_pct=expected_edge_pct,
        notional_usd=notional_usd,
        wmatic_balance=wmatic_balance,
        extra=extra,
    )
    print(f"{runtime._nanolog()}{line}")
    logger.info(line)
    if state is not None and counter_field:
        bump_counter(state, str(branch).strip().upper(), counter_field)
    return line


def log_x_signal_decision(
    symbol: str,
    action: str,
    reason: str,
    *,
    signal: float | None = None,
    expected_edge_pct: float | None = None,
    notional_usd: float | None = None,
    wmatic_balance: float | None = None,
    extra: str = "",
    state: dict | None = None,
    bump_symbol_counter: bool = True,
) -> str:
    """X-SIGNAL accept/reject with legacy alias line for existing log parsers."""
    act = str(action).strip().upper()
    counter_field: str | None = None
    if bump_symbol_counter:
        if act == _ACTION_ACCEPT:
            counter_field = "taken"
        elif act == _ACTION_REJECT:
            counter_field = "skipped"
    line = log_decision(
        branch=_BRANCH_X_SIGNAL,
        action=act,
        reason=reason,
        symbol=symbol,
        signal_strength=signal,
        expected_edge_pct=expected_edge_pct,
        notional_usd=notional_usd,
        wmatic_balance=wmatic_balance,
        extra=extra,
        state=state,
        counter_field=counter_field,
    )
    # Backward-compatible alias (subset of fields) for scripts that grep X-SIGNAL DECISION.
    sym = str(symbol).strip() or "?"
    rsn = str(reason).strip() or "unknown"
    sig_part = f" | signal={float(signal):.3f}" if signal is not None else ""
    tail = f" | {extra.strip()}" if extra.strip() else ""
    alias = f"X-SIGNAL DECISION | symbol={sym} | action={act} | reason={rsn}{sig_part}{tail}"
    print(f"{runtime._nanolog()}{alias}")
    logger.info(alias)
    return line


def record_x_signal_cycle_outcome(
    state: dict | None,
    *,
    taken: bool,
    reason: str,
    wmatic_balance: float | None = None,
) -> None:
    """Once per cycle: X-SIGNAL branch produced an executable plan vs not."""
    field = "cycle_taken" if taken else "cycle_skipped"
    bump_counter(state, _BRANCH_X_SIGNAL, field)
    log_decision(
        branch=_BRANCH_X_SIGNAL,
        action=_ACTION_ACCEPT if taken else _ACTION_REJECT,
        reason=reason,
        wmatic_balance=wmatic_balance,
        extra=f"scope=cycle",
        state=state,
    )


def log_profit_take_decision(
    *,
    action: str,
    reason: str,
    signal_strength: float | None = None,
    expected_edge_pct: float | None = None,
    notional_usd: float | None = None,
    wmatic_balance: float | None = None,
    extra: str = "",
    state: dict | None = None,
) -> str:
    """Open-trade / cycle profit-take evaluation (evaluate_take_profit, swap_executor paths)."""
    act = str(action).strip().upper()
    counter_field: str | None = None
    if act == _ACTION_TAKE:
        counter_field = "take_signal"
    elif act == _ACTION_HOLD:
        counter_field = "hold"
    elif act == _ACTION_DEFER:
        counter_field = "deferred"
    elif act == _ACTION_REJECT:
        counter_field = "rejected"
    return log_decision(
        branch=_BRANCH_PROFIT_TAKE,
        action=act,
        reason=reason,
        signal_strength=signal_strength,
        expected_edge_pct=expected_edge_pct,
        notional_usd=notional_usd,
        wmatic_balance=wmatic_balance,
        extra=extra,
        state=state,
        counter_field=counter_field,
    )


def log_main_strategy_decision(
    *,
    action: str,
    reason: str,
    direction: str = "",
    signal_strength: float | None = None,
    expected_edge_pct: float | None = None,
    notional_usd: float | None = None,
    wmatic_balance: float | None = None,
    wmatic_usd: float | None = None,
    extra: str = "",
    state: dict | None = None,
) -> str:
    """Main-strategy WMATIC band exits (reserve / take-profit / cut-loss / buy defer)."""
    act = str(action).strip().upper()
    counter_field: str | None = None
    if act == _ACTION_TAKE and str(direction).strip().upper() in {"WMATIC_TO_USDT", "WMATIC_TO_USDC"}:
        counter_field = "profit_exit_planned"
    elif act == _ACTION_REJECT:
        counter_field = "skipped"
    tail_bits = [extra.strip()] if extra.strip() else []
    if direction:
        tail_bits.append(f"direction={direction}")
    if wmatic_usd is not None:
        tail_bits.append(f"wmatic_usd={float(wmatic_usd):.2f}")
    return log_decision(
        branch=_BRANCH_MAIN_STRATEGY,
        action=act,
        reason=reason,
        signal_strength=signal_strength,
        expected_edge_pct=expected_edge_pct,
        notional_usd=notional_usd,
        wmatic_balance=wmatic_balance,
        extra=" | ".join(tail_bits),
        state=state,
        counter_field=counter_field,
    )


def record_profit_take_execution(state: dict | None, *, success: bool, reason: str = "swap_ok") -> None:
    """After on-chain WMATIC→stable swap attempt (success rate numerator/denominator)."""
    bump_counter(state, _BRANCH_PROFIT_TAKE, "executed_attempts")
    if success:
        bump_counter(state, _BRANCH_PROFIT_TAKE, "executed_success")
    else:
        bump_counter(state, _BRANCH_PROFIT_TAKE, "executed_failed")
    log_decision(
        branch=_BRANCH_PROFIT_TAKE,
        action=_ACTION_EXECUTE if success else _ACTION_REJECT,
        reason=reason,
        extra=f"success={success}",
        state=None,
    )


def profit_take_success_rate(tracking: Mapping[str, Any] | None) -> float | None:
    """Basic success rate = executed_success / executed_attempts."""
    if not tracking:
        return None
    pt = tracking.get(_BRANCH_PROFIT_TAKE) if isinstance(tracking, dict) else None
    if not isinstance(pt, dict):
        return None
    attempts = int(pt.get("executed_attempts", 0) or 0)
    if attempts <= 0:
        return None
    success = int(pt.get("executed_success", 0) or 0)
    return success / float(attempts)


def format_tracking_summary(state: dict | None) -> str:
    """Single-line rollup for end-of-cycle or daily grep."""
    root = decision_tracking_state(state)
    xs = root.get(_BRANCH_X_SIGNAL) if isinstance(root.get(_BRANCH_X_SIGNAL), dict) else {}
    pt = root.get(_BRANCH_PROFIT_TAKE) if isinstance(root.get(_BRANCH_PROFIT_TAKE), dict) else {}
    ms = root.get(_BRANCH_MAIN_STRATEGY) if isinstance(root.get(_BRANCH_MAIN_STRATEGY), dict) else {}
    rate = profit_take_success_rate(root)
    rate_s = f"{rate * 100:.1f}%" if rate is not None else "n/a"
    return (
        "DECISION_TRACKING | "
        f"x_signal_taken={int(xs.get('taken', 0) or 0)} "
        f"x_signal_skipped={int(xs.get('skipped', 0) or 0)} "
        f"x_signal_cycle_taken={int(xs.get('cycle_taken', 0) or 0)} "
        f"x_signal_cycle_skipped={int(xs.get('cycle_skipped', 0) or 0)} "
        f"profit_take_hold={int(pt.get('hold', 0) or 0)} "
        f"profit_take_take_signal={int(pt.get('take_signal', 0) or 0)} "
        f"profit_take_executed_success={int(pt.get('executed_success', 0) or 0)} "
        f"profit_take_executed_attempts={int(pt.get('executed_attempts', 0) or 0)} "
        f"profit_take_success_rate={rate_s} "
        f"main_strategy_profit_exit_planned={int(ms.get('profit_exit_planned', 0) or 0)}"
    )


def log_tracking_summary(state: dict | None) -> str:
    """Print persisted decision counters (learning/adaptation telemetry)."""
    line = format_tracking_summary(state)
    print(f"{runtime._nanolog()}{line}")
    logger.info(line)
    return line
