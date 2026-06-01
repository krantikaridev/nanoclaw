"""Adverse-day churn guard — log-only v1 + runtime flag for future throttle (Agent Q).

When the adverse window is red and fills meet ``PNL_ADVERSE_DAY_MIN_FILLS``, logs
``ADVERSE CHURN GUARD`` and persists ``.runtime/adverse_churn_flag.json`` with a
soft-cap recommendation. Does **not** change trading, gates, or pause state in v1.

v2 (Agent Q): ``read_recommended_notional_mult()`` / ``load_adverse_churn_flag()``
may halve tiered max notional and X-SIGNAL buy sizing when ``active`` is true.
See ``docs/OPERATOR_PNL_MARK_VS_TRADE.md`` § Adverse churn guard.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any

from nanoclaw.pnl_adverse_day import (
    AdverseDayMetrics,
    pnl_adverse_day_min_fills,
)

ADVERSE_CHURN_FLAG_FILE = Path(".runtime/adverse_churn_flag.json")
_GUARD_LOG_PREFIX = "[nanoclaw] ADVERSE CHURN GUARD"


def _parse_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_env_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except ValueError:
        return default
    if not math.isfinite(value) or value <= 0.0:
        return default
    return value


def adverse_churn_guard_enabled() -> bool:
    return _parse_env_bool("ADVERSE_CHURN_GUARD_ENABLED", default=False)


def adverse_churn_guard_fill_mult() -> float:
    """Recommended notional multiplier when guard is active (v2 throttle hook)."""
    return _parse_env_positive_float("ADVERSE_CHURN_GUARD_FILL_MULT", 0.5)


def _state_path(path: Path | None = None) -> Path:
    return path or ADVERSE_CHURN_FLAG_FILE


def should_trigger_guard(metrics: AdverseDayMetrics) -> bool:
    """True when window is red and fill count meets the adverse-day floor."""
    if not metrics.is_adverse:
        return False
    return int(metrics.fill_count) >= pnl_adverse_day_min_fills()


def build_flag_payload(
    metrics: AdverseDayMetrics,
    *,
    active: bool,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    mult = adverse_churn_guard_fill_mult()
    return {
        "active": bool(active),
        "recommended_notional_mult": float(mult),
        "window_hours": float(metrics.window_hours),
        "fill_count": int(metrics.fill_count),
        "min_fills": int(pnl_adverse_day_min_fills()),
        "total_delta_usd": float(metrics.total_delta_usd),
        "mark_delta_usd": float(metrics.mark_delta_usd),
        "churn_cost_est_usd": float(metrics.churn_cost_est_usd),
        "turnover_usd": float(metrics.turnover_usd),
        "updated_at": now.isoformat(),
    }


def _save_flag(payload: dict[str, Any], path: Path | None = None) -> None:
    file_path = _state_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_adverse_churn_flag(path: Path | None = None) -> dict[str, Any]:
    """Load persisted guard state; empty dict when missing or invalid."""
    file_path = _state_path(path)
    if not file_path.is_file():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def guard_active(path: Path | None = None) -> bool:
    """v2 hook: True when the runtime flag recommends throttling new entries."""
    if not adverse_churn_guard_enabled():
        return False
    state = load_adverse_churn_flag(path)
    return bool(state.get("active"))


def read_recommended_notional_mult(*, path: Path | None = None, default: float = 1.0) -> float:
    """v2 hook for Agent Q / drawdown throttle: mult when active, else ``default``."""
    if not guard_active(path):
        return float(default)
    state = load_adverse_churn_flag(path)
    try:
        mult = float(state.get("recommended_notional_mult", adverse_churn_guard_fill_mult()))
    except (TypeError, ValueError):
        mult = adverse_churn_guard_fill_mult()
    if not math.isfinite(mult) or mult <= 0.0:
        return float(default)
    return float(mult)


def format_guard_log_line(metrics: AdverseDayMetrics) -> str:
    mult = adverse_churn_guard_fill_mult()
    return (
        f"{_GUARD_LOG_PREFIX} | total_delta=${metrics.total_delta_usd:+.2f} | "
        f"fills={metrics.fill_count} | recommended_notional_mult={mult:.2f}"
    )


def evaluate_and_persist(
    metrics: AdverseDayMetrics,
    *,
    now_utc: datetime | None = None,
    flag_path: Path | None = None,
    log_fn: Any = print,
) -> bool:
    """Update runtime flag from adverse metrics; log when guard triggers. Returns ``active``."""
    if not adverse_churn_guard_enabled():
        return False
    active = should_trigger_guard(metrics)
    payload = build_flag_payload(metrics, active=active, now_utc=now_utc)
    _save_flag(payload, flag_path)
    if active:
        log_fn(format_guard_log_line(metrics))
    return active


def maybe_refresh_from_metrics(
    metrics: AdverseDayMetrics | None,
    *,
    flag_path: Path | None = None,
    log_fn: Any = print,
) -> bool:
    """No-op when disabled or metrics missing; otherwise ``evaluate_and_persist``."""
    if not adverse_churn_guard_enabled() or metrics is None:
        return False
    return evaluate_and_persist(metrics, flag_path=flag_path, log_fn=log_fn)
