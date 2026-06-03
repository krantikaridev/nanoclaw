"""Window-stress de-risk — relaxed DERISK gates when auto-paused for window PnL only.

When ``EXTERNAL_AUTO_PAUSE_ENABLED`` pauses entries for the 12h window floor only
(``auto_pause | window PnL below …``), optional ``WINDOW_STRESS_DERISK_*`` knobs
allow capped EQUITY→USDC trims at lower FE share / higher WMATIC than static
``FE_STABLE_RUNWAY_DERISK_*``. Entries and tiered BUY remain blocked by pause;
tiered cooldown and ``EXTERNAL_AUTO_WINDOW_MIN_PCT`` are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import config as cfg

_WINDOW_PAUSE_SUBSTR = "window PnL below"


@dataclass(frozen=True)
class WindowStressDeriskOverrides:
    """Relaxed DERISK thresholds while window-only auto_pause is active."""

    min_fe_share: float
    max_wmatic_usd: float


def _enabled() -> bool:
    return bool(getattr(cfg, "WINDOW_STRESS_DERISK_ENABLED", False))


def _min_fe_share() -> float:
    return float(getattr(cfg, "WINDOW_STRESS_DERISK_MIN_FE_SHARE", 0.72))


def _max_wmatic_usd() -> float:
    return float(getattr(cfg, "WINDOW_STRESS_DERISK_MAX_WMATIC_USD", 12.0))


def is_window_pnl_pause_reason(reason: str | None) -> bool:
    """True when external layer paused for the configurable window PnL floor."""
    if not reason or not str(reason).strip():
        return False
    text = str(reason).strip()
    return _WINDOW_PAUSE_SUBSTR in text and text.startswith("auto_pause")


def resolve_window_stress_derisk(
    *,
    paused: bool,
    reason: str | None,
) -> WindowStressDeriskOverrides | None:
    """Return relaxed thresholds when window-only auto_pause is active."""
    if not _enabled():
        return None
    if not paused:
        return None
    if not is_window_pnl_pause_reason(reason):
        return None
    return WindowStressDeriskOverrides(
        min_fe_share=_min_fe_share(),
        max_wmatic_usd=_max_wmatic_usd(),
    )
