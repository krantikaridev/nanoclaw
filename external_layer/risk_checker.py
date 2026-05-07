"""Risk assessment hooks for the external layer — live Polygon balances via Web3."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

# Tier thresholds (USDT / WMATIC human balances from Polygon).
_CRITICAL_USDT = 60.0
_CRITICAL_WMATIC = 50.0
_MODERATE_USDT = 85.0
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


def get_wallet_balances() -> tuple[float, float]:
    """Return current USDT and WMATIC balances (human amounts) for ``WALLET`` on Polygon.

    Uses ``nanoclaw.config.connect_web3()`` so RPC follows the same precedence as the bot
    (``RPC`` / ``RPC_ENDPOINTS`` / public fallbacks from env).
    """
    from web3 import Web3

    import config as cfg
    from nanoclaw.config import connect_web3

    w3 = connect_web3()
    wallet = Web3.to_checksum_address(cfg.WALLET)
    usdt_addr = Web3.to_checksum_address(cfg.USDT)
    wmatic_addr = Web3.to_checksum_address(cfg.WMATIC)

    usdt_c = w3.eth.contract(address=usdt_addr, abi=_ERC20_BALANCE_ABI)
    wmatic_c = w3.eth.contract(address=wmatic_addr, abi=_ERC20_BALANCE_ABI)

    usdt_raw = usdt_c.functions.balanceOf(wallet).call()
    wmatic_raw = wmatic_c.functions.balanceOf(wallet).call()

    # Polygon USDT uses 6 decimals; WMATIC uses 18.
    usdt = float(usdt_raw) / 1_000_000
    wmatic = float(wmatic_raw) / 1e18
    return (usdt, wmatic)


def evaluate_risk(
    *,
    usdt_balance: float | None = None,
    wmatic_balance: float | None = None,
) -> dict[str, bool | str | float]:
    """Decide pause state, copy-trade cap, and reason from wallet balances.

    By default reads live balances via ``get_wallet_balances()``. When both
    ``usdt_balance`` and ``wmatic_balance`` are passed (e.g. unit tests), those
    values are used instead of RPC.

    Returns ``paused``, ``max_copy_trade_pct`` (0.02–0.10), ``reason``, plus
    ``usdt_balance`` / ``wmatic_balance`` for logging.

    Rules:
    - USDT < 60 or WMATIC < 50 → paused, cap 0.02
    - Else USDT < 85 or WMATIC < 65 → not paused, cap 0.03
    - Else → not paused, cap 0.06
    """
    if usdt_balance is not None and wmatic_balance is not None:
        usdt = float(usdt_balance)
        wmatic = float(wmatic_balance)
    else:
        usdt, wmatic = get_wallet_balances()

    global _FORCE_MIN_UNTIL_TS
    critical = usdt < _CRITICAL_USDT or wmatic < _CRITICAL_WMATIC
    moderate = usdt < _MODERATE_USDT or wmatic < _MODERATE_WMATIC
    now = time.time()

    # Extra defensive rule: if the last 3 evaluations were in a protected tier
    # (Critical or Moderate), clamp copy size to 2% for the next 10 minutes.
    protected = critical or moderate
    _RECENT_PROTECTION_EVALS.append((now, protected))
    recent = list(_RECENT_PROTECTION_EVALS)[-3:]
    if len(recent) == 3 and all(is_protected for _, is_protected in recent):
        _FORCE_MIN_UNTIL_TS = max(_FORCE_MIN_UNTIL_TS, now + 10 * 60)
    force_min = now < _FORCE_MIN_UNTIL_TS

    if critical:
        paused = True
        max_pct = _clamp_copy_pct(0.02)
        reason = (
            "Critical low balance: trading paused; copy trades capped at 2% "
            f"(USDT<{_CRITICAL_USDT} or WMATIC<{_CRITICAL_WMATIC})"
        )
    elif moderate:
        paused = False
        max_pct = _clamp_copy_pct(0.03)
        reason = (
            "Moderate low balance: trading allowed; copy trades capped at 3% "
            f"(USDT<{_MODERATE_USDT} or WMATIC<{_MODERATE_WMATIC})"
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
