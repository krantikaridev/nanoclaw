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
_MODERATE_STABLE_USD = 85.0
_MODERATE_WMATIC = 65.0

# Copy-trade cap bounds written to ``control.json`` (fraction of portfolio logic).
_MIN_COPY_PCT = 0.02
_MAX_COPY_PCT = 0.10


def _clamp_copy_pct(pct: float) -> float:
    return max(_MIN_COPY_PCT, min(_MAX_COPY_PCT, float(pct)))


# In-memory guardrail: if we see repeated low-balance protection, temporarily clamp size.
_RECENT_PROTECTION_EVALS: deque[tuple[float, bool]] = deque(maxlen=5)
_FORCE_MIN_UNTIL_TS: float = 0.0

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

    Rules (stable runway = USDT + USDC; unchanged WMATIC gas runway):
    - stable_usd < 60 or WMATIC < 50 → paused, cap 0.02
    - Else stable_usd < 85 or WMATIC < 65 → not paused, cap 0.03
    - Else → not paused, cap 0.06
    """
    if usdt_balance is not None and wmatic_balance is not None:
        usdt = float(usdt_balance)
        usdc = float(0.0 if usdc_balance is None else usdc_balance)
        wmatic = float(wmatic_balance)
    else:
        usdt, usdc, wmatic = get_wallet_balances()

    stable_usd = usdt + usdc

    global _FORCE_MIN_UNTIL_TS
    critical = stable_usd < _CRITICAL_STABLE_USD or wmatic < _CRITICAL_WMATIC
    moderate = stable_usd < _MODERATE_STABLE_USD or wmatic < _MODERATE_WMATIC
    now = time.time()

    # Extra defensive rule: if the last 3 evaluations were in a protected tier
    # (Critical or Moderate), clamp copy size to 2% for the next 10 minutes.
    protected = critical or moderate
    _RECENT_PROTECTION_EVALS.append((now, protected))
    recent = list(_RECENT_PROTECTION_EVALS)[-3:]
    # Arm the streak clamp only while stable runway is still below the Moderate USD
    # threshold; once stable_usd >= _MODERATE_STABLE_USD, drop the timer so we do not
    # keep a 2% cap (and misleading "clamp" reason) after total stables have recovered.
    if len(recent) == 3 and all(is_protected for _, is_protected in recent):
        if stable_usd < _MODERATE_STABLE_USD:
            _FORCE_MIN_UNTIL_TS = max(_FORCE_MIN_UNTIL_TS, now + 10 * 60)
    if stable_usd >= _MODERATE_STABLE_USD:
        _FORCE_MIN_UNTIL_TS = 0.0
    force_min = now < _FORCE_MIN_UNTIL_TS

    if critical:
        paused = True
        max_pct = _clamp_copy_pct(0.02)
        reason = (
            "Critical low balance: trading paused; copy trades capped at 2% "
            f"(USDT+USDC<{_CRITICAL_STABLE_USD} or WMATIC<{_CRITICAL_WMATIC})"
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

    if force_min and max_pct > _MIN_COPY_PCT:
        max_pct = _clamp_copy_pct(0.02)
        reason = f"{reason}; defensive clamp active (recent low-balance streak)"

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
