"""Cap X-SIGNAL max trade when the 12h portfolio window is negative."""

from __future__ import annotations

from pathlib import Path

import config as cfg

_LOG_PREFIX = "[nanoclaw] X-SIGNAL NEGATIVE WINDOW CAP"


def _enabled() -> bool:
    return bool(getattr(cfg, "X_SIGNAL_NEGATIVE_WINDOW_CAP_ENABLED", False))


def _window_hours() -> float:
    return float(getattr(cfg, "X_SIGNAL_NEGATIVE_WINDOW_CAP_HOURS", 12.0))


def _max_trade_usd() -> float:
    return float(getattr(cfg, "X_SIGNAL_NEGATIVE_WINDOW_MAX_TRADE_USD", 10.0))


def resolve_window_pnl_pct(
    *,
    current_total: float | None = None,
    history_path: Path | None = None,
) -> float | None:
    from nanoclaw.drawdown_throttle import resolve_window_pnl_pct as _resolve

    return _resolve(
        current_total=current_total,
        hours=_window_hours(),
        history_path=history_path,
    )


def resolve_effective_max_trade_usd(
    base_max_usd: float,
    *,
    window_pct: float | None = None,
    current_total: float | None = None,
    history_path: Path | None = None,
) -> float:
    """Return min(base, cap) when 12h window PnL is below 0%; otherwise base."""
    base = float(base_max_usd)
    if not _enabled():
        return base
    pct = (
        window_pct
        if window_pct is not None
        else resolve_window_pnl_pct(current_total=current_total, history_path=history_path)
    )
    if pct is None or float(pct) + 1e-9 >= 0.0:
        return base
    cap = min(base, _max_trade_usd())
    if cap + 1e-9 < base:
        print(
            f"{_LOG_PREFIX} | window={float(pct):+.2f}% | "
            f"max_trade ${base:.2f} → ${cap:.2f}",
            flush=True,
        )
    return cap
