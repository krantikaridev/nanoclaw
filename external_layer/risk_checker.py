"""Risk assessment hooks for the external layer — live Polygon USDT, USDC (combined), WMATIC."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

# Tier thresholds: **stable runway** uses USDT + USDC (both dollar stables); gas runway
# stays on WMATIC alone. Mirrors ``runtime.get_balances()`` / STABLE_USD — pausing because
# USDT alone hit $0 while USDC stayed healthy blocked trading unnecessarily (2026-05-07).
_CRITICAL_STABLE_USD = 60.0
_CRITICAL_WMATIC = 50.0
_MODERATE_STABLE_USD = 100.0
_MODERATE_WMATIC = 65.0
# REVERSIBLE travel tune (2026-05-09): when USDT+USDC ≥ this, ease pause frequency (WMATIC floor)
# and keep copy caps ≥ ~4.5% instead of falling to the 2% streak clamp so often.
_TRAVEL_HIGH_STABLE_USD = 95.0
_CRITICAL_WMATIC_WHEN_STABLE_HIGH = 45.0
_TRAVEL_RELAX_MIN_COPY_PCT = 0.045

# Copy-trade cap bounds written to ``control.json`` (fraction of portfolio logic).
_MIN_COPY_PCT = 0.02
_MAX_COPY_PCT = 0.10


def _clamp_copy_pct(pct: float) -> float:
    return max(_MIN_COPY_PCT, min(_MAX_COPY_PCT, float(pct)))


def _stable_runway_tier_rank(stable_usd: float) -> int:
    """Discrete stable-runway tier for clamp hysteresis (0=critical, 1=moderate, 2=healthy)."""
    if stable_usd < _CRITICAL_STABLE_USD:
        return 0
    if stable_usd < _MODERATE_STABLE_USD:
        return 1
    return 2


# In-memory guardrail: if we see repeated low-balance protection, temporarily clamp size.
_RECENT_PROTECTION_EVALS: deque[tuple[float, bool, float]] = deque(maxlen=5)
_FORCE_MIN_UNTIL_TS: float = 0.0
# Worst ``stable_usd`` seen while the streak clamp timer is active (for early release vs tier).
_CLAMP_STREAK_MIN_STABLE_USD: float | None = None

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
      (threshold is 50 when stable_usd < $95, else 45 — reversible travel tune 2026-05-09).
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

    global _FORCE_MIN_UNTIL_TS, _CLAMP_STREAK_MIN_STABLE_USD
    wmatic_pause_threshold = (
        _CRITICAL_WMATIC
        if stable_usd < _TRAVEL_HIGH_STABLE_USD
        else _CRITICAL_WMATIC_WHEN_STABLE_HIGH
    )
    critical = stable_usd < _CRITICAL_STABLE_USD or wmatic < wmatic_pause_threshold
    moderate = stable_usd < _MODERATE_STABLE_USD or wmatic < _MODERATE_WMATIC
    now = time.time()

    # Extra defensive rule: if the last 3 evaluations were in a protected tier
    # (Critical or Moderate), temporarily clamp copy size (2% legacy; 4.5% when stables ≥ $95).
    protected = critical or moderate
    _RECENT_PROTECTION_EVALS.append((now, protected, stable_usd))
    recent = list(_RECENT_PROTECTION_EVALS)[-3:]
    # Arm the streak clamp only while stable runway is still below the Moderate USD
    # threshold; once stable_usd >= _MODERATE_STABLE_USD, drop the timer so we do not
    # keep a 2% cap (and misleading "clamp" reason) after total stables have recovered.
    if len(recent) == 3 and all(is_protected for _, is_protected, _ in recent):
        if stable_usd < _MODERATE_STABLE_USD:
            _FORCE_MIN_UNTIL_TS = max(_FORCE_MIN_UNTIL_TS, now + 10 * 60)
            streak_cand = min(s for _, _, s in recent)
            # Keep the worst stable seen for this cooldown so rolling the deque cannot
            # erase a prior critical dip and re-trigger the full 2% clamp spuriously.
            if _CLAMP_STREAK_MIN_STABLE_USD is None:
                _CLAMP_STREAK_MIN_STABLE_USD = streak_cand
            else:
                _CLAMP_STREAK_MIN_STABLE_USD = min(_CLAMP_STREAK_MIN_STABLE_USD, streak_cand)
    if stable_usd >= _MODERATE_STABLE_USD:
        _FORCE_MIN_UNTIL_TS = 0.0
        _CLAMP_STREAK_MIN_STABLE_USD = None
    force_min = now < _FORCE_MIN_UNTIL_TS
    if not force_min:
        _CLAMP_STREAK_MIN_STABLE_USD = None

    if critical:
        paused = True
        max_pct = _clamp_copy_pct(0.02)
        reason = (
            "Critical low balance: trading paused; copy trades capped at 2% "
            f"(USDT+USDC<{_CRITICAL_STABLE_USD} or WMATIC<{wmatic_pause_threshold})"
        )
    elif moderate:
        paused = False
        max_pct = _clamp_copy_pct(0.03)
        reason = (
            "Moderate low balance: trading allowed; copy trades capped at 3% "
            f"(USDT+USDC<{_MODERATE_STABLE_USD} or WMATIC<{_MODERATE_WMATIC})"
        )
    else:
        paused = False
        max_pct = _clamp_copy_pct(0.06)
        reason = "Healthy balance: copy trades capped at 6%"

    # Full 2% streak clamp still prevents whiplash after repeated protected reads, but if
    # total stables have recovered into a strictly better runway tier than the worst
    # stable level in that arming streak (e.g. critical → moderate), keep the tier cap
    # (3% / 6%) instead of forcing 2% until stable_usd hits 85 or the timer expires.
    if force_min and max_pct > _MIN_COPY_PCT:
        streak_min = _CLAMP_STREAK_MIN_STABLE_USD
        early_release = streak_min is not None and _stable_runway_tier_rank(
            stable_usd
        ) > _stable_runway_tier_rank(streak_min)
        if not early_release:
            # REVERSIBLE: below $95 stables, keep legacy 2% streak clamp; at/above, floor at 4.5%.
            streak_floor = (
                _TRAVEL_RELAX_MIN_COPY_PCT
                if stable_usd >= _TRAVEL_HIGH_STABLE_USD
                else _MIN_COPY_PCT
            )
            max_pct = _clamp_copy_pct(streak_floor)
            reason = f"{reason}; defensive clamp active (recent low-balance streak)"

    # Healthy runway: never write a copy cap below 4.5% unless we are in true critical pause.
    if stable_usd >= _TRAVEL_HIGH_STABLE_USD and not critical:
        max_pct = _clamp_copy_pct(max(float(max_pct), _TRAVEL_RELAX_MIN_COPY_PCT))

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
