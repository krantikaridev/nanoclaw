"""Risk assessment hooks for the external layer — live Polygon balances via Web3."""

from __future__ import annotations

from typing import Any

# Minimum balances before we ask nanoclaw to pause new entries via ``control.json``.
_MIN_USDT = 50.0
_MIN_WMATIC = 40.0

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
    """Decide whether external risk rules should pause trading.

    By default reads live balances via ``get_wallet_balances()``. When both
    ``usdt_balance`` and ``wmatic_balance`` are passed (e.g. unit tests), those
    values are used instead of RPC.

    Returns a dict consumed by ``external_layer.control.update_control``:
    ``paused``, optional ``reason``, and ``usdt_balance`` / ``wmatic_balance``
    for operator logging.
    """
    if usdt_balance is not None and wmatic_balance is not None:
        usdt = float(usdt_balance)
        wmatic = float(wmatic_balance)
    else:
        usdt, wmatic = get_wallet_balances()

    paused = usdt < _MIN_USDT or wmatic < _MIN_WMATIC
    out: dict[str, bool | str | float] = {
        "paused": paused,
        "usdt_balance": usdt,
        "wmatic_balance": wmatic,
    }
    if paused:
        out["reason"] = "Low balance protection"
    return out


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
