"""Risk assessment hooks for the external layer — live Polygon USDT, USDC (combined), WMATIC."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from external_layer.clamp_policy import (
    clamp_log_prefix,
    get_risk_policy,
    reload_risk_policy_for_tests,
)

# In-memory guardrail: if we see repeated low-balance protection, temporarily clamp size.
_RECENT_PROTECTION_EVALS: deque[tuple[float, bool, float]] = deque(
    maxlen=get_risk_policy().clamp.deque_maxlen
)


def _reset_protection_eval_deque() -> None:
    """Rebuild deque maxlen after policy reload (unit tests)."""
    global _RECENT_PROTECTION_EVALS
    _RECENT_PROTECTION_EVALS = deque(maxlen=get_risk_policy().clamp.deque_maxlen)


def _clamp_copy_pct(pct: float) -> float:
    c = get_risk_policy().clamp
    return max(c.min_copy_pct, min(c.max_copy_pct, float(pct)))


def _stable_runway_tier_rank(stable_usd: float) -> int:
    """Discrete stable-runway tier for clamp hysteresis (0=critical, 1=moderate, 2=healthy)."""
    tier = get_risk_policy().tier
    if stable_usd < tier.critical_stable_usd:
        return 0
    if stable_usd < tier.moderate_stable_usd:
        return 1
    return 2
_FORCE_MIN_UNTIL_TS: float = 0.0
# Worst ``stable_usd`` seen while the streak clamp timer is active (for early release vs tier).
_CLAMP_STREAK_MIN_STABLE_USD: float | None = None

# Previous-cycle snapshot for clamp observability (edge-triggered ON/OFF/RELAX logs).
_CLAMP_LOG_PREV: dict[str, bool] = {
    "timer_active": False,
    "overlay_active": False,
}


def _reset_clamp_log_state() -> None:
    """Clear clamp log edge state (unit tests)."""
    _CLAMP_LOG_PREV["timer_active"] = False
    _CLAMP_LOG_PREV["overlay_active"] = False


def _protected_streak_label(recent: list[tuple[float, bool, float]]) -> str:
    n = sum(1 for _, is_prot, _ in recent if is_prot)
    need = get_risk_policy().clamp.streak_evals
    return f"{n}/{need}"


def _log_defensive_clamp(event: str, **fields: object) -> None:
    """Stdout trace for operators; matches ``[EXTERNAL]`` control-layer prefix."""
    bits = [f"{clamp_log_prefix()} {event}"]
    for key, val in fields.items():
        if val is None:
            continue
        if isinstance(val, float):
            if key.endswith("_pct"):
                bits.append(f"{key}={val:.4f}")
            elif key == "wmatic_balance":
                bits.append(f"{key}={val:.4f}")
            elif key == "timer_remaining_s":
                bits.append(f"{key}={val:.0f}")
            else:
                bits.append(f"{key}={val:.2f}")
        elif isinstance(val, bool):
            bits.append(f"{key}={'true' if val else 'false'}")
        else:
            bits.append(f"{key}={val}")
    print(" | ".join(bits), flush=True)


def _emit_defensive_clamp_observability(
    *,
    now: float,
    stable_usd: float,
    wmatic: float,
    critical: bool,
    moderate: bool,
    protected: bool,
    recent: list[tuple[float, bool, float]],
    force_min: bool,
    until_ts: float,
    streak_min_stable: float | None,
    tier_pct: float,
    max_pct: float,
    overlay_active: bool,
    early_release: bool,
    timer_armed_this_eval: bool,
    timer_cleared_this_eval: bool,
    clear_reason: str | None,
    reason: str,
) -> None:
    prev_timer = bool(_CLAMP_LOG_PREV["timer_active"])
    prev_overlay = bool(_CLAMP_LOG_PREV["overlay_active"])
    remain_s = max(0.0, float(until_ts) - float(now)) if force_min else 0.0
    common: dict[str, object] = {
        "stable_usd": stable_usd,
        "wmatic_balance": wmatic,
        "protected_streak": _protected_streak_label(recent),
        "protected": protected,
        "critical": critical,
        "moderate": moderate,
    }

    if timer_armed_this_eval:
        _log_defensive_clamp(
            "ON",
            detail="timer_armed",
            timer_remaining_s=remain_s,
            streak_min_stable=streak_min_stable,
            **common,
        )

    if timer_cleared_this_eval and (prev_timer or prev_overlay):
        _log_defensive_clamp(
            "OFF",
            detail=clear_reason or "timer_cleared",
            max_copy_trade_pct=max_pct,
            tier_cap_pct=tier_pct,
            **common,
        )

    if overlay_active and not prev_overlay:
        reduced = max_pct < tier_pct - 1e-9
        _log_defensive_clamp(
            "ON",
            detail="clamp_overlay",
            max_copy_trade_pct=max_pct,
            tier_cap_pct=tier_pct,
            timer_remaining_s=remain_s,
            streak_min_stable=streak_min_stable,
            early_release=False,
            **common,
        )
        if reduced:
            _log_defensive_clamp(
                "CAP_REDUCED",
                max_copy_trade_pct=max_pct,
                tier_cap_pct=tier_pct,
                delta_pct=tier_pct - max_pct,
                reason_snippet="defensive clamp active",
                **common,
            )
    elif overlay_active and prev_overlay:
        _log_defensive_clamp(
            "STAY",
            max_copy_trade_pct=max_pct,
            tier_cap_pct=tier_pct,
            timer_remaining_s=remain_s,
            streak_min_stable=streak_min_stable,
            reason=reason,
            **common,
        )
    elif prev_overlay and not overlay_active:
        relax_detail = "early_release" if early_release else "overlay_cleared"
        _log_defensive_clamp(
            "RELAX" if early_release else "OFF",
            detail=relax_detail,
            max_copy_trade_pct=max_pct,
            tier_cap_pct=tier_pct,
            streak_min_stable=streak_min_stable,
            **common,
        )

    _CLAMP_LOG_PREV["timer_active"] = bool(force_min)
    _CLAMP_LOG_PREV["overlay_active"] = bool(overlay_active)


# Minimal ERC-20 ``balanceOf`` ABI for USDT / WMATIC reads.
_ERC20_BALANCE_ABI: list[dict[str, Any]] = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


def get_wallet_balances() -> tuple[float, float, float]:
    """Return ``(usdt, usdc_total, wmatic)`` human balances for ``WALLET`` on Polygon.

    ``usdc_total`` is USDC.e (``cfg.USDC``) plus native USDC when it is a different
    contract (same rule as ``runtime._total_usdc_balance``).

    Uses ``nanoclaw.config.connect_web3()`` so RPC follows the same precedence as the bot
    (``RPC`` / ``RPC_ENDPOINTS`` / public fallbacks from env).
    """
    from web3 import Web3

    import config as cfg
    from nanoclaw.config import connect_web3

    w3 = connect_web3()
    wallet = Web3.to_checksum_address(cfg.WALLET)
    usdt_addr = Web3.to_checksum_address(cfg.USDT)
    usdc_addr = Web3.to_checksum_address(cfg.USDC)
    wmatic_addr = Web3.to_checksum_address(cfg.WMATIC)

    usdt_c = w3.eth.contract(address=usdt_addr, abi=_ERC20_BALANCE_ABI)
    usdc_c = w3.eth.contract(address=usdc_addr, abi=_ERC20_BALANCE_ABI)
    wmatic_c = w3.eth.contract(address=wmatic_addr, abi=_ERC20_BALANCE_ABI)

    usdt_raw = usdt_c.functions.balanceOf(wallet).call()
    usdc_raw = usdc_c.functions.balanceOf(wallet).call()
    wmatic_raw = wmatic_c.functions.balanceOf(wallet).call()

    # Polygon USDT / USDC use 6 decimals; WMATIC uses 18.
    usdt = float(usdt_raw) / 1_000_000
    usdc_total = float(usdc_raw) / 1_000_000
    native_raw = getattr(cfg, "USDC_NATIVE", "") or ""
    native = str(native_raw).strip()
    base_usdc = str(cfg.USDC).strip()
    if native and native.lower() != base_usdc.lower():
        native_c = w3.eth.contract(
            address=Web3.to_checksum_address(native),
            abi=_ERC20_BALANCE_ABI,
        )
        usdc_total += float(native_c.functions.balanceOf(wallet).call()) / 1_000_000
    wmatic = float(wmatic_raw) / 1e18
    return (usdt, usdc_total, wmatic)


def evaluate_risk(
    *,
    usdt_balance: float | None = None,
    usdc_balance: float | None = None,
    wmatic_balance: float | None = None,
) -> dict[str, bool | str | float]:
    """Decide pause state, copy-trade cap, and reason from wallet balances.

    By default reads live balances via ``get_wallet_balances()``. When both
    ``usdt_balance`` and ``wmatic_balance`` are passed (e.g. unit tests), those
    values are used instead of RPC. Optional ``usdc_balance`` augments injected
    stables (defaults to ``0`` when omitted so legacy tests stay meaningful).

    Returns ``paused``, ``max_copy_trade_pct`` (0.02–0.10), ``reason``, plus
    ``usdt_balance``, ``usdc_balance`` (combined USDC contracts),
    ``stable_usd`` (USDT + that USDC), and ``wmatic_balance`` for logging.

    Rules (stable runway = USDT + USDC; WMATIC gas runway):
    - stable_usd < 60 or WMATIC below tier threshold → paused, cap 0.02
      (WMATIC floor is 50 only when stable_usd < $60; else 10 — TEMPORARY 2026-05-23).
    - Else stable_usd < 100 or WMATIC < 65 → not paused, cap 0.03 (raised to ≥4.5% if stables ≥ $95)
    - Else → not paused, cap 0.06 (same ≥4.5% floor when stables ≥ $95)
    """
    if usdt_balance is not None and wmatic_balance is not None:
        usdt = float(usdt_balance)
        usdc = float(0.0 if usdc_balance is None else usdc_balance)
        wmatic = float(wmatic_balance)
    else:
        usdt, usdc, wmatic = get_wallet_balances()

    stable_usd = usdt + usdc
    policy = get_risk_policy()
    tier = policy.tier
    clamp = policy.clamp

    global _FORCE_MIN_UNTIL_TS, _CLAMP_STREAK_MIN_STABLE_USD
    wmatic_pause_threshold = (
        tier.critical_wmatic
        if stable_usd < tier.critical_stable_usd
        else tier.critical_wmatic_when_stable_ok
    )
    critical = stable_usd < tier.critical_stable_usd or wmatic < wmatic_pause_threshold
    moderate = (
        stable_usd < tier.moderate_stable_usd or wmatic < tier.moderate_wmatic
    )
    now = time.time()

    protected = critical or moderate
    _RECENT_PROTECTION_EVALS.append((now, protected, stable_usd))
    recent = list(_RECENT_PROTECTION_EVALS)[-clamp.streak_evals :]

    prev_until_ts = float(_FORCE_MIN_UNTIL_TS)
    timer_cleared_this_eval = False
    clear_reason: str | None = None

    if stable_usd >= clamp.healthy_stable_usd and wmatic >= clamp.recovery_wmatic:
        if prev_until_ts > now:
            timer_cleared_this_eval = True
            clear_reason = "healthy_stable_runway"
        _FORCE_MIN_UNTIL_TS = 0.0
        _CLAMP_STREAK_MIN_STABLE_USD = None
    elif stable_usd >= clamp.recovery_stable_usd and not critical:
        if prev_until_ts > now:
            timer_cleared_this_eval = True
            clear_reason = "travel_stable_recovery"
        _FORCE_MIN_UNTIL_TS = 0.0
        _CLAMP_STREAK_MIN_STABLE_USD = None

    timer_armed_this_eval = False
    if len(recent) == clamp.streak_evals and all(
        is_protected for _, is_protected, _ in recent
    ):
        if stable_usd < tier.moderate_stable_usd and (
            stable_usd < clamp.arm_max_stable_usd or critical
        ):
            if stable_usd < clamp.arm_max_stable_usd:
                _FORCE_MIN_UNTIL_TS = max(
                    _FORCE_MIN_UNTIL_TS, now + clamp.duration_sec
                )
            elif _FORCE_MIN_UNTIL_TS <= now:
                _FORCE_MIN_UNTIL_TS = now + clamp.duration_sec
            if _FORCE_MIN_UNTIL_TS > prev_until_ts:
                timer_armed_this_eval = True
            streak_cand = min(s for _, _, s in recent)
            if _CLAMP_STREAK_MIN_STABLE_USD is None:
                _CLAMP_STREAK_MIN_STABLE_USD = streak_cand
            else:
                _CLAMP_STREAK_MIN_STABLE_USD = min(
                    _CLAMP_STREAK_MIN_STABLE_USD, streak_cand
                )

    force_min = now < _FORCE_MIN_UNTIL_TS
    if not force_min:
        _CLAMP_STREAK_MIN_STABLE_USD = None

    if critical:
        paused = True
        max_pct = _clamp_copy_pct(tier.tier_critical_copy_pct)
        reason = (
            "Critical low balance: trading paused; copy trades capped at 2% "
            f"(USDT+USDC<{tier.critical_stable_usd} or WMATIC<{wmatic_pause_threshold})"
        )
    elif moderate:
        paused = False
        max_pct = _clamp_copy_pct(tier.tier_moderate_copy_pct)
        reason = (
            "Moderate low balance: trading allowed; copy trades capped at 3% "
            f"(USDT+USDC<{tier.moderate_stable_usd} or WMATIC<{tier.moderate_wmatic})"
        )
    else:
        paused = False
        max_pct = _clamp_copy_pct(tier.tier_healthy_copy_pct)
        reason = "Healthy balance: copy trades capped at 6%"

    tier_pct = float(max_pct)
    overlay_active = False
    early_release = False
    if force_min and max_pct > clamp.min_copy_pct:
        streak_min = _CLAMP_STREAK_MIN_STABLE_USD
        early_release = streak_min is not None and _stable_runway_tier_rank(
            stable_usd
        ) > _stable_runway_tier_rank(streak_min)
        if not early_release:
            streak_floor = (
                clamp.travel_floor_pct
                if stable_usd >= tier.travel_stable_usd
                else clamp.streak_floor_pct
            )
            max_pct = _clamp_copy_pct(streak_floor)
            reason = f"{reason}; defensive clamp active (recent low-balance streak)"
            overlay_active = True

    if stable_usd >= tier.travel_stable_usd and not critical:
        max_pct = _clamp_copy_pct(max(float(max_pct), tier.travel_min_copy_pct))

    _emit_defensive_clamp_observability(
        now=now,
        stable_usd=stable_usd,
        wmatic=wmatic,
        critical=critical,
        moderate=moderate,
        protected=protected,
        recent=recent,
        force_min=force_min,
        until_ts=float(_FORCE_MIN_UNTIL_TS),
        streak_min_stable=_CLAMP_STREAK_MIN_STABLE_USD,
        tier_pct=tier_pct,
        max_pct=float(max_pct),
        overlay_active=overlay_active,
        early_release=early_release,
        timer_armed_this_eval=timer_armed_this_eval,
        timer_cleared_this_eval=timer_cleared_this_eval,
        clear_reason=clear_reason,
        reason=reason,
    )

    return {
        "paused": paused,
        "max_copy_trade_pct": max_pct,
        "reason": reason,
        "usdt_balance": usdt,
        "usdc_balance": usdc,
        "stable_usd": stable_usd,
        "wmatic_balance": wmatic,
    }


def get_current_risk_state() -> str:
    """Return a coarse risk label for the portfolio / market context.

    Eventually this will aggregate volatility, drawdown, liquidity, and other
    signals into LOW / MEDIUM / HIGH (or similar). For now it is a fixed stub.
    """
    return "MEDIUM"


def should_pause() -> bool:
    """Whether external risk rules say trading should halt this cycle.

    Eventually this will combine ``get_current_risk_state()``, control file
    flags, and live telemetry. For now it always allows execution.
    """
    return False


def get_recommended_max_size() -> float:
    """Suggested maximum position/copy fraction under current risk.

    Eventually this will tighten or loosen caps based on risk state and
    ``ControlCommand.max_copy_trade_pct``. For now it matches the default cap.
    """
    return 0.08
