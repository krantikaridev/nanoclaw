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
        "synthetic": False,
    }


def get_equity_entry(state: dict | None, symbol: str) -> dict[str, Any] | None:
    if state is None:
        return None
    raw = _entries_root(state).get(str(symbol).strip().upper())
    return raw if isinstance(raw, dict) else None


def resolve_live_spot_usd(
    *,
    fallback_price_usd: float | None,
    equity_balance: float,
    token_address: str,
    token_decimals: int,
    mode: str = "default",
) -> float | None:
    """Live spot per token: on-chain quote first, then ``current_price_usd`` fallback.

    ``mode='loss_cut'`` caps quotes far above FE fallback (drained-pool / size-impact
    misquotes) so underwater trims are not suppressed by an inflated live spot.
    """
    if equity_balance <= 0 and (fallback_price_usd is None or float(fallback_price_usd) <= 0):
        return None
    fallback = (
        float(fallback_price_usd)
        if fallback_price_usd is not None and float(fallback_price_usd) > 0
        else None
    )
    quote_usd: float | None = None
    try:
        from modules import runtime as rt

        slip = int(getattr(cfg, "INVENTORY_MTM_SLIPPAGE_BPS", 300))
        one_unit = int(10 ** int(token_decimals))
        raw_quote = rt._quote_followed_token_usdt_mtm(
            rt.w3,
            token_in=str(token_address).strip(),
            amount_in_raw=one_unit,
            slippage_bps=slip,
        )
        if raw_quote > 0:
            quote_usd = float(raw_quote)
    except Exception:
        pass
    if quote_usd is not None and quote_usd > 0:
        if (
            str(mode).strip().lower() == "loss_cut"
            and fallback is not None
            and quote_usd > fallback * float(
                getattr(cfg, "HIGH_RISK_LOSS_CUT_SPOT_SANITY_MULT", 1.35)
            )
        ):
            return fallback
        return quote_usd
    if fallback is not None:
        return fallback
    return None


def resolve_entry_price_usd(
    state: dict | None,
    symbol: str,
    *,
    fallback_price_usd: float | None = None,
    live_spot_usd: float | None = None,
) -> tuple[float | None, bool]:
    """
    Entry price for underwater math.

    Returns (price, synthetic_bootstrap). Persisted fills win; otherwise estimate
    cost above FE floor when the position predates entry tracking.
    """
    sym = str(symbol).strip().upper()
    entry = get_equity_entry(state, sym)
    if entry is not None:
        px = float(entry.get("entry_price_usd", 0.0) or 0.0)
        if px > 0:
            return px, bool(entry.get("synthetic"))
    if fallback_price_usd is None or float(fallback_price_usd) <= 0:
        return None, False
    premium = float(getattr(cfg, "HIGH_RISK_LOSS_CUT_BOOTSTRAP_ENTRY_PREMIUM_PCT", 12.0))
    base = float(fallback_price_usd)
    if live_spot_usd is not None and float(live_spot_usd) > 0:
        base = max(base, float(live_spot_usd))
    return base * (1.0 + premium / 100.0), True


def underwater_context(
    state: dict | None,
    symbol: str,
    *,
    fallback_price_usd: float | None,
    live_spot_usd: float | None,
) -> tuple[bool, float | None, float | None, float | None, bool]:
    """
    Returns (is_underwater, entry_px, spot_px, loss_pct, entry_synthetic).

    Underwater when ``spot < entry * (1 - LOSS_PCT/100)``.
    """
    if not allow_high_risk_loss_cut_xsignal():
        return False, None, None, None, False
    sym = str(symbol).strip().upper()
    if sym not in loss_cut_symbols():
        return False, None, None, None, False
    spot_px = live_spot_usd
    if spot_px is None or spot_px <= 0:
        return False, None, None, None, False
    entry_px, entry_synthetic = resolve_entry_price_usd(
        state,
        sym,
        fallback_price_usd=fallback_price_usd,
        live_spot_usd=spot_px,
    )
    if entry_px is None or entry_px <= 0:
        return False, None, spot_px, None, False
    loss_pct = (float(entry_px) - float(spot_px)) / float(entry_px) * 100.0
    threshold = float(getattr(cfg, "HIGH_RISK_LOSS_CUT_LOSS_PCT", 3.0))
    return float(loss_pct) + 1e-9 >= threshold, entry_px, spot_px, loss_pct, entry_synthetic


def loss_cut_portfolio_eligible(*, total_portfolio_usd: float) -> bool:
    if not allow_high_risk_loss_cut_xsignal():
        return False
    min_pf = float(getattr(cfg, "HIGH_RISK_LOSS_CUT_MIN_PORTFOLIO_USD", 130.0))
    return float(total_portfolio_usd) > min_pf


def loss_cut_cycle_eligible(
    *,
    risk_level: str,
    total_portfolio_usd: float,
    has_underwater_position: bool = False,
) -> bool:
    if not loss_cut_portfolio_eligible(total_portfolio_usd=total_portfolio_usd):
        return False
    risk = str(risk_level).strip().upper()
    if risk == "HIGH":
        return True
    if (
        bool(getattr(cfg, "HIGH_RISK_LOSS_CUT_WHEN_UNDERWATER_ANY_RISK", True))
        and has_underwater_position
    ):
        return True
    return False


def is_underwater_symbol(
    state: dict | None,
    symbol: str,
    *,
    fallback_price_usd: float | None,
    live_spot_usd: float | None,
) -> bool:
    underwater, _, _, _, _ = underwater_context(
        state,
        symbol,
        fallback_price_usd=fallback_price_usd,
        live_spot_usd=live_spot_usd,
    )
    return underwater


def loss_cut_sell_fraction() -> float:
    frac = float(getattr(cfg, "HIGH_RISK_LOSS_CUT_SELL_FRACTION", 0.55))
    return min(1.0, max(0.05, frac))
