"""Risk assessment hooks for the external layer."""

from __future__ import annotations

# --- Placeholder balances (replace with live RPC / wallet reads later) ---
_PLACEHOLDER_USDT_BALANCE = 100.0
_PLACEHOLDER_WMATIC_BALANCE = 100.0

# Minimum balances before we ask nanoclaw to pause new entries via ``control.json``.
_MIN_USDT = 50.0
_MIN_WMATIC = 50.0


def evaluate_risk(
    *,
    usdt_balance: float | None = None,
    wmatic_balance: float | None = None,
) -> dict[str, bool | str]:
    """Decide whether external risk rules should pause trading.

    Reads USDT (USD-stable) and WMATIC balances. Uses module placeholders when
    callers omit values so the external layer can run before RPC wiring exists.

    Returns a small dict consumed by ``external_layer.control.update_control``:
    ``{"paused": True, "reason": "..."}`` or ``{"paused": False}``.
    """
    # Resolve balances: explicit overrides (e.g. tests) or placeholder defaults.
    usdt = float(_PLACEHOLDER_USDT_BALANCE if usdt_balance is None else usdt_balance)
    wmatic = float(_PLACEHOLDER_WMATIC_BALANCE if wmatic_balance is None else wmatic_balance)

    if usdt < _MIN_USDT or wmatic < _MIN_WMATIC:
        return {"paused": True, "reason": "Low balance"}

    return {"paused": False}


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
