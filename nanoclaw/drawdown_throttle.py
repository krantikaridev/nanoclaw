"""Portfolio drawdown throttle — halve tiered / X-SIGNAL buy sizing on window loss.

Uses the same ``portfolio_history.csv`` window math as ``scripts/nano_green.py``.
Only new-entry sizing hooks (``fe_stable_runway_tiered_cap_notional_usd``,
``apply_buy_size_multiplier``); protection exits (derisk, rebuild, loss-cut) are
unchanged.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config as cfg

_LOG_PREFIX = "[nanoclaw] DRAWDOWN THROTTLE"


@dataclass(frozen=True)
class DrawdownThrottleState:
    """Resolved drawdown throttle for the current cycle."""

    active: bool
    window_pct: float | None
    notional_mult: float


def _enabled() -> bool:
    return bool(getattr(cfg, "DRAWDOWN_THROTTLE_ENABLED", False))


def _window_hours() -> float:
    return float(getattr(cfg, "DRAWDOWN_THROTTLE_WINDOW_HOURS", 8.0))


def _trigger_pct() -> float:
    return float(getattr(cfg, "DRAWDOWN_THROTTLE_TRIGGER_PCT", -1.0))


def _notional_mult() -> float:
    raw = float(getattr(cfg, "DRAWDOWN_THROTTLE_NOTIONAL_MULT", 0.5))
    if raw <= 0.0:
        return 0.5
    return raw


def _default_history_path() -> Path:
    from scripts.pnl_report import PORTFOLIO_HISTORY_FILE

    return Path(PORTFOLIO_HISTORY_FILE)


def _parse_iso_ts(raw: str) -> datetime | None:
    from scripts.pnl_report import _parse_iso_ts as parse_ts

    return parse_ts(raw)


def resolve_history_at_or_before(
    cutoff_utc: datetime,
    *,
    csv_path: Path | None = None,
) -> tuple[float | None, datetime | None]:
    """Last portfolio_history row with timestamp <= cutoff (same semantics as pnl_report)."""
    path = csv_path or _default_history_path()
    if not path.is_file():
        return None, None
    best_total: float | None = None
    best_ts: datetime | None = None
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    total = float(row.get("total_value", ""))
                except (TypeError, ValueError):
                    continue
                if ts <= cutoff_utc:
                    best_ts = ts
                    best_total = total
    except OSError:
        return None, None
    if best_total is None or best_ts is None:
        return None, None
    return float(best_total), best_ts


def resolve_window_pnl_pct(
    *,
    current_total: float | None = None,
    now_utc: datetime | None = None,
    hours: float | None = None,
    history_path: Path | None = None,
) -> float | None:
    """Window PnL %% vs portfolio_history (same math as nano_green / unpause_hysteresis)."""
    if current_total is None:
        from scripts.pnl_report import get_current_balance

        bal = get_current_balance()
        if not bal:
            return None
        current_total = float(bal["total"])

    lookback = float(hours if hours is not None else _window_hours())
    now = now_utc or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback)
    ref, ref_ts = resolve_history_at_or_before(cutoff, csv_path=history_path)
    if ref is None or ref_ts is None:
        return None
    delta = float(current_total) - float(ref)
    return (delta / float(ref) * 100.0) if ref else 0.0


def resolve_drawdown_throttle(
    *,
    window_pct: float | None = None,
    now_utc: datetime | None = None,
    current_total: float | None = None,
    history_path: Path | None = None,
) -> DrawdownThrottleState:
    """Return active throttle state; inactive when disabled or window data missing."""
    if not _enabled():
        return DrawdownThrottleState(active=False, window_pct=window_pct, notional_mult=1.0)

    pct = (
        window_pct
        if window_pct is not None
        else resolve_window_pnl_pct(
            current_total=current_total,
            now_utc=now_utc,
            history_path=history_path,
        )
    )
    if pct is None:
        return DrawdownThrottleState(active=False, window_pct=None, notional_mult=1.0)

    trigger = _trigger_pct()
    active = float(pct) + 1e-9 < float(trigger)
    mult = _notional_mult() if active else 1.0
    return DrawdownThrottleState(active=active, window_pct=float(pct), notional_mult=float(mult))


def log_drawdown_throttle(*, window_pct: float, tiered_max_usd: float) -> None:
    print(
        f"{_LOG_PREFIX} | window={float(window_pct):+.1f}% | "
        f"tiered_max=${float(tiered_max_usd):.2f}"
    )


def _entry_notional_mult(
    state: DrawdownThrottleState,
    *,
    include_adverse_churn: bool = True,
) -> float:
    mult = float(state.notional_mult)
    if include_adverse_churn:
        try:
            from nanoclaw.adverse_churn_guard import read_recommended_notional_mult

            mult *= float(read_recommended_notional_mult(default=1.0))
        except Exception:
            pass
    return mult


def apply_tiered_max_throttle(
    tiered_max_usd: float,
    *,
    window_pct: float | None = None,
    current_total: float | None = None,
    history_path: Path | None = None,
    now_utc: datetime | None = None,
) -> float:
    """Scale tiered max notional when drawdown throttle is active."""
    state = resolve_drawdown_throttle(
        window_pct=window_pct,
        current_total=current_total,
        history_path=history_path,
        now_utc=now_utc,
    )
    mult = _entry_notional_mult(state)
    if mult + 1e-9 >= 1.0:
        return float(tiered_max_usd)
    throttled = float(tiered_max_usd) * mult
    if state.active and state.window_pct is not None:
        log_drawdown_throttle(window_pct=state.window_pct, tiered_max_usd=throttled)
    return throttled


def apply_buy_size_multiplier(
    buy_mult: float,
    *,
    window_pct: float | None = None,
    current_total: float | None = None,
    history_path: Path | None = None,
    now_utc: datetime | None = None,
) -> float:
    """Scale X-SIGNAL buy multiplier for new entries; skips when already zero."""
    mult = float(buy_mult)
    if mult <= 0.0:
        return mult
    state = resolve_drawdown_throttle(
        window_pct=window_pct,
        current_total=current_total,
        history_path=history_path,
        now_utc=now_utc,
    )
    combined = _entry_notional_mult(state)
    if combined + 1e-9 >= 1.0:
        return mult
    return mult * combined
