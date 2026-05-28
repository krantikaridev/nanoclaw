"""X-SIGNAL equity entry tracking and HIGH-risk loss-cut eligibility."""

from __future__ import annotations

import time
from typing import Any, Optional

import config as cfg

_X_SIGNAL_EQUITY_ENTRIES_KEY = "x_signal_equity_entries"


def _entries_root(state: dict | None) -> dict:
    if state is None:
        return {}
    return state.setdefault(_X_SIGNAL_EQUITY_ENTRIES_KEY, {})


def allow_high_risk_loss_cut_xsignal() -> bool:
    return bool(getattr(cfg, "ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL", True))


def loss_cut_symbols() -> frozenset[str]:
    return frozenset(getattr(cfg, "HIGH_RISK_LOSS_CUT_SYMBOLS", frozenset({"LINK_ALPHA"})))


def loss_cut_block_buys() -> bool:
    return bool(getattr(cfg, "HIGH_RISK_LOSS_CUT_BLOCK_BUYS", True))


def record_equity_entry(
    state: dict,
    symbol: str,
    *,
    entry_price_usd: float,
    notional_usd: float,
    tx_hash: str,
) -> None:
    """Persist last X-SIGNAL USDC→equity fill for underwater / loss-cut checks."""
    sym = str(symbol).strip().upper()
    if not sym or float(entry_price_usd) <= 0:
        return
    root = _entries_root(state)
    root[sym] = {
        "entry_price_usd": float(entry_price_usd),
        "notional_usd": float(notional_usd),
        "entry_ts": float(time.time()),
        "tx_hash": str(tx_hash),
    }


def get_equity_entry(state: dict | None, symbol: str) -> dict[str, Any] | None:
    if state is None:
        return None
    raw = _entries_root(state).get(str(symbol).strip().upper())
    return raw if isinstance(raw, dict) else None


def resolve_entry_price_usd(
    state: dict | None,
    symbol: str,
    *,
    fallback_price_usd: float | None = None,
) -> float | None:
    """
    Entry price for underwater math.

    Uses persisted fill price when present; otherwise bootstraps from
    ``followed_equities.json`` ``current_price_usd`` for existing holdings.
    """
    entry = get_equity_entry(state, symbol)
    if entry is not None:
        px = float(entry.get("entry_price_usd", 0.0) or 0.0)
        if px > 0:
            return px
    if fallback_price_usd is not None and float(fallback_price_usd) > 0:
        return float(fallback_price_usd)
    return None


def resolve_live_spot_usd(
    *,
    fallback_price_usd: float | None,
    equity_balance: float,
    token_address: str,
    token_decimals: int,
) -> float | None:
    """Best-effort spot USD per token unit (fallback floor from followed_equities when quote unavailable)."""
    if fallback_price_usd is not None and float(fallback_price_usd) > 0:
        return float(fallback_price_usd)
    if equity_balance <= 0:
        return None
    try:
        from modules import runtime as rt

        slip = int(getattr(cfg, "INVENTORY_MTM_SLIPPAGE_BPS", 300))
        one_unit = int(10 ** int(token_decimals))
        quote_usd = rt._quote_followed_token_usdt_mtm(
            rt.w3,
            token_in=str(token_address).strip(),
            amount_in_raw=one_unit,
            slippage_bps=slip,
        )
        if quote_usd > 0:
            return float(quote_usd)
    except Exception:
        pass
    return None


def underwater_context(
    state: dict | None,
    symbol: str,
    *,
    fallback_price_usd: float | None,
    live_spot_usd: float | None,
) -> tuple[bool, float | None, float | None, float | None]:
    """
    Returns (is_underwater, entry_px, spot_px, loss_pct).

    Underwater when ``spot < entry * (1 - LOSS_PCT/100)``.
    """
    if not allow_high_risk_loss_cut_xsignal():
        return False, None, None, None
    sym = str(symbol).strip().upper()
    if sym not in loss_cut_symbols():
        return False, None, None, None
    entry_px = resolve_entry_price_usd(state, sym, fallback_price_usd=fallback_price_usd)
    if entry_px is None or entry_px <= 0:
        return False, None, None, None
    spot_px = live_spot_usd
    if spot_px is None or spot_px <= 0:
        return False, entry_px, None, None
    loss_pct = (float(entry_px) - float(spot_px)) / float(entry_px) * 100.0
    threshold = float(getattr(cfg, "HIGH_RISK_LOSS_CUT_LOSS_PCT", 3.0))
    return float(loss_pct) + 1e-9 >= threshold, entry_px, spot_px, loss_pct


def loss_cut_cycle_eligible(
    *,
    risk_level: str,
    total_portfolio_usd: float,
) -> bool:
    if not allow_high_risk_loss_cut_xsignal():
        return False
    if str(risk_level).strip().upper() != "HIGH":
        return False
    min_pf = float(getattr(cfg, "HIGH_RISK_LOSS_CUT_MIN_PORTFOLIO_USD", 130.0))
    return float(total_portfolio_usd) > min_pf


def is_underwater_symbol(
    state: dict | None,
    symbol: str,
    *,
    fallback_price_usd: float | None,
    live_spot_usd: float | None,
) -> bool:
    underwater, _, _, _ = underwater_context(
        state,
        symbol,
        fallback_price_usd=fallback_price_usd,
        live_spot_usd=live_spot_usd,
    )
    return underwater


def loss_cut_sell_fraction() -> float:
    frac = float(getattr(cfg, "HIGH_RISK_LOSS_CUT_SELL_FRACTION", 0.55))
    return min(1.0, max(0.05, frac))
