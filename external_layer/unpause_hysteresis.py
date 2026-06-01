"""Consecutive-tick hysteresis before auto_unpause (reduces pause/unpause whipsaw)."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_above_buffer_streak: int = 0


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        try:
            import config as cfg

            return bool(getattr(cfg, name, default))
        except Exception:
            return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        try:
            import config as cfg

            return float(getattr(cfg, name, default))
        except Exception:
            return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        try:
            import config as cfg

            return int(getattr(cfg, name, default))
        except Exception:
            return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def unpause_hysteresis_enabled() -> bool:
    return _env_bool("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED", False)


def unpause_hysteresis_ticks_required() -> int:
    return max(1, _env_int("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS", 6))


def unpause_window_buffer_pct() -> float:
    return _env_float("EXTERNAL_AUTO_UNPAUSE_WINDOW_BUFFER_PCT", 0.25)


def hysteresis_window_floor_pct(window_min_pct: float) -> float:
    """Stricter window floor for streak counting (base floor + buffer)."""
    return float(window_min_pct) + unpause_window_buffer_pct()


def reset_unpause_hysteresis_for_tests() -> None:
    """Clear module streak (unit tests)."""
    global _above_buffer_streak
    _above_buffer_streak = 0


def unpause_hysteresis_streak() -> int:
    return _above_buffer_streak


def resolve_window_pnl_pct(root: Path | None = None, *, hours: float) -> float | None:
    """12h (or configured) window PnL %% from portfolio_history; None if unavailable."""
    from datetime import datetime, timedelta, timezone

    from scripts.pnl_report import _resolve_history_at_or_before, get_current_balance

    root = root or Path(os.environ.get("NANOCLAW_ROOT", str(_REPO_ROOT)))
    bal = get_current_balance()
    if not bal:
        return None
    current_total = float(bal["total"])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(hours))
    ref, ref_ts = _resolve_history_at_or_before(cutoff)
    if ref is None or ref_ts is None:
        return None
    delta = current_total - float(ref)
    return (delta / float(ref) * 100.0) if ref else 0.0


def _tick_streak(window_pct: float | None, *, window_min_pct: float) -> None:
    global _above_buffer_streak
    floor = hysteresis_window_floor_pct(window_min_pct)
    if window_pct is not None and window_pct + 1e-9 >= floor:
        _above_buffer_streak += 1
    else:
        _above_buffer_streak = 0


def format_hysteresis_log(window_pct: float | None) -> str:
    required = unpause_hysteresis_ticks_required()
    streak = unpause_hysteresis_streak()
    if window_pct is None:
        window_part = "n/a"
    else:
        window_part = f"{window_pct:+.1f}%"
    return (
        f"[external] auto_unpause hysteresis | ticks={streak}/{required} | "
        f"window={window_part}"
    )


def record_unpause_hysteresis_tick(
    *,
    root: Path | None = None,
    hours: float,
    window_min_pct: float,
) -> float | None:
    """Advance streak on each external-layer tick; return window PnL %% if known."""
    root = root or Path(os.environ.get("NANOCLAW_ROOT", str(_REPO_ROOT)))
    window_pct = resolve_window_pnl_pct(root, hours=hours)
    if unpause_hysteresis_enabled():
        _tick_streak(window_pct, window_min_pct=window_min_pct)
    return window_pct


def hysteresis_blocks_unpause() -> bool:
    if not unpause_hysteresis_enabled():
        return False
    return unpause_hysteresis_streak() < unpause_hysteresis_ticks_required()


def apply_unpause_hysteresis(
    would_unpause: bool,
    *,
    window_pct: float | None = None,
) -> tuple[bool, str | None]:
    """After ``record_unpause_hysteresis_tick``, block unpause until streak is satisfied."""
    if not would_unpause:
        return False, None
    if not hysteresis_blocks_unpause():
        return True, None
    return False, format_hysteresis_log(window_pct)
