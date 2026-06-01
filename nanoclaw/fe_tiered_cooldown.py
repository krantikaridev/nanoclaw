"""Tiered FE stable-runway re-entry cooldown — block capped USDC→EQUITY after rebuild/tiered fill."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import config as cfg

FE_TIERED_COOLDOWN_FILE = Path(".runtime/fe_tiered_cooldown.json")
_COOLDOWN_LOG_PREFIX = "[nanoclaw] FE STABLE RUNWAY TIERED | cooldown"


def _cooldown_enabled() -> bool:
    return bool(getattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED", True))


def _cooldown_hours() -> float:
    raw = float(getattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_HOURS", 4.0))
    if not math.isfinite(raw) or raw <= 0.0:
        return 4.0
    return raw


def _cooldown_after_rebuild() -> bool:
    return bool(getattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_AFTER_REBUILD", True))


def _state_path(path: Path | None = None) -> Path:
    return path or FE_TIERED_COOLDOWN_FILE


def _load_state(path: Path | None = None) -> dict:
    file_path = _state_path(path)
    if not file_path.is_file():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_state(state: dict, path: Path | None = None) -> None:
    file_path = _state_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _format_until_iso(until_ts: float) -> str:
    dt = datetime.fromtimestamp(float(until_ts), tz=timezone.utc)
    return dt.isoformat()


def cooldown_until_ts(*, now: float | None = None, state_path: Path | None = None) -> float | None:
    """Return active cooldown expiry epoch seconds, or None when inactive/disabled."""
    if not _cooldown_enabled():
        return None
    state = _load_state(state_path)
    until = float(state.get("cooldown_until_ts") or 0.0)
    if until <= 0.0:
        return None
    now_ts = float(now if now is not None else datetime.now(timezone.utc).timestamp())
    if now_ts + 1e-9 >= until:
        return None
    return until


def cooldown_active(*, now: float | None = None, state_path: Path | None = None) -> bool:
    return cooldown_until_ts(now=now, state_path=state_path) is not None


def record_cooldown(
    *,
    trigger: str,
    stable_usd: float,
    now: float | None = None,
    state_path: Path | None = None,
) -> float | None:
    """Start or extend tiered re-entry cooldown; return new ``until`` epoch seconds."""
    if not _cooldown_enabled():
        return None
    now_ts = float(now if now is not None else datetime.now(timezone.utc).timestamp())
    hours = _cooldown_hours()
    until = now_ts + hours * 3600.0
    state = _load_state(state_path)
    prev_until = float(state.get("cooldown_until_ts") or 0.0)
    state["cooldown_until_ts"] = max(until, prev_until)
    state["last_trigger"] = str(trigger or "").strip() or "unknown"
    state["last_stable_usd"] = float(stable_usd)
    state["cooldown_hours"] = hours
    _save_state(state, state_path)
    return float(state["cooldown_until_ts"])


def log_cooldown_defer(*, stable_usd: float, until_ts: float) -> None:
    print(
        f"{_COOLDOWN_LOG_PREFIX} | stable_usd={float(stable_usd):.2f} | "
        f"until={_format_until_iso(until_ts)}"
    )


def maybe_defer_tiered_bypass(
    stable_usd: float,
    *,
    now: float | None = None,
    state_path: Path | None = None,
) -> bool:
    """Return True when tiered bypass should be blocked due to active cooldown."""
    until = cooldown_until_ts(now=now, state_path=state_path)
    if until is None:
        return False
    log_cooldown_defer(stable_usd=float(stable_usd), until_ts=until)
    return True


def maybe_record_rebuild_cooldown(
    *,
    stable_usd: float,
    now: float | None = None,
    state_path: Path | None = None,
) -> float | None:
    """Set cooldown after successful WMATIC→stable rebuild when env toggle is on."""
    if not _cooldown_after_rebuild():
        return None
    return record_cooldown(
        trigger="rebuild",
        stable_usd=float(stable_usd),
        now=now,
        state_path=state_path,
    )


def maybe_record_tiered_fill_cooldown(
    *,
    stable_usd: float,
    now: float | None = None,
    state_path: Path | None = None,
) -> float | None:
    """Set cooldown after successful tiered USDC→EQUITY fill."""
    return record_cooldown(
        trigger="tiered_fill",
        stable_usd=float(stable_usd),
        now=now,
        state_path=state_path,
    )
