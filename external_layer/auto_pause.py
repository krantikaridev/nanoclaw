"""Portfolio-driven auto pause/unpause for external_layer → control.json."""

from __future__ import annotations

import os
from pathlib import Path

from nanoclaw.runtime_state import OPERATOR_PAUSE_LOCK_KEY

_REPO_ROOT = Path(__file__).resolve().parent.parent


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


def auto_pause_enabled() -> bool:
    return _env_bool("EXTERNAL_AUTO_PAUSE_ENABLED", False)


def evaluate_auto_pause() -> tuple[bool, str, tuple[str, ...]]:
    """Return (trading_allowed, reason, rotation_open_symbols)."""
    from scripts.nano_green import evaluate_green_gate

    root = Path(os.environ.get("NANOCLAW_ROOT", str(_REPO_ROOT)))
    hours = _env_float("EXTERNAL_AUTO_GREEN_HOURS", 12.0)
    session_min = _env_float("EXTERNAL_AUTO_SESSION_MIN_PCT", -1.0)
    window_min = _env_float("EXTERNAL_AUTO_WINDOW_MIN_PCT", -2.0)
    result = evaluate_green_gate(
        root,
        hours=hours,
        session_min_pct=session_min,
        window_min_pct=window_min,
    )
    if result.trading_allowed() and result.overall_pass:
        rot = ", ".join(result.rotation_open) or "none"
        reason = (
            f"auto_unpause | window={hours:.0f}h | session≥{session_min:+.1f}% | "
            f"rotation={rot}"
        )
        return True, reason, result.rotation_open
    if not result.readiness_pass:
        reason = "auto_pause | hard readiness gate failed"
    elif not result.session_pass:
        reason = f"auto_pause | session below {session_min:+.1f}% floor"
    elif not result.pause_pass:
        reason = "auto_pause | fill while paused (discipline breach)"
    else:
        reason = f"auto_pause | window PnL below {window_min:+.1f}% over {hours:.0f}h"
    return False, reason, result.rotation_open


def apply_auto_pause_control(payload: dict[str, object]) -> dict[str, object]:
    """When enabled, set ``paused`` from portfolio gates (replaces manual leave pause)."""
    if not auto_pause_enabled():
        return payload
    allowed, reason, rotation = evaluate_auto_pause()
    merged = dict(payload)
    merged["paused"] = not allowed
    merged["auto_pause_control"] = True
    merged[OPERATOR_PAUSE_LOCK_KEY] = False
    merged["reason"] = reason
    if rotation:
        merged["rotation_open"] = list(rotation)
    return merged
