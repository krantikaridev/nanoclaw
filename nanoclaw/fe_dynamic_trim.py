"""Dynamic FE-share bands for FE stable-runway de-risk max trim."""

from __future__ import annotations

from dataclasses import dataclass

import config as cfg

_DERISK_LOG_PREFIX = "[nanoclaw] FE STABLE RUNWAY DERISK"


@dataclass(frozen=True)
class DeriskDynamicTrim:
    """Resolved de-risk trim caps for a given FE share."""

    max_trim_usd: float | None
    min_fe_share: float
    dynamic_trim_usd: float | None


def _dynamic_enabled() -> bool:
    return bool(getattr(cfg, "FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED", False))


def _low_fe_share() -> float:
    return float(getattr(cfg, "FE_STABLE_RUNWAY_DERISK_LOW_FE_SHARE", 0.70))


def _high_fe_share() -> float:
    return float(getattr(cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_SHARE", 0.85))


def _high_fe_max_trim_usd() -> float:
    return float(getattr(cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_MAX_TRIM_USD", 15.0))


def resolve_derisk_dynamic_trim(
    fe_share: float,
    *,
    default_max_trim_usd: float,
    default_min_fe_share: float,
) -> DeriskDynamicTrim:
    """Return effective max trim and min FE share for de-risk context."""
    fe = float(fe_share)
    default_max = float(default_max_trim_usd)
    default_min = float(default_min_fe_share)

    if not _dynamic_enabled():
        return DeriskDynamicTrim(
            max_trim_usd=default_max,
            min_fe_share=default_min,
            dynamic_trim_usd=None,
        )

    low_fe = _low_fe_share()
    if fe + 1e-9 < low_fe:
        log_dynamic_trim(fe_share=fe, dynamic_trim_usd=None)
        return DeriskDynamicTrim(
            max_trim_usd=None,
            min_fe_share=default_min,
            dynamic_trim_usd=None,
        )

    high_fe = _high_fe_share()
    if fe > high_fe + 1e-9:
        high_max = _high_fe_max_trim_usd()
        log_dynamic_trim(fe_share=fe, dynamic_trim_usd=high_max)
        return DeriskDynamicTrim(
            max_trim_usd=high_max,
            min_fe_share=low_fe,
            dynamic_trim_usd=high_max,
        )

    log_dynamic_trim(fe_share=fe, dynamic_trim_usd=default_max)
    return DeriskDynamicTrim(
        max_trim_usd=default_max,
        min_fe_share=default_min,
        dynamic_trim_usd=default_max,
    )


def log_dynamic_trim(*, fe_share: float, dynamic_trim_usd: float | None) -> None:
    if not _dynamic_enabled():
        return
    if dynamic_trim_usd is None:
        print(
            f"{_DERISK_LOG_PREFIX} | evaluate | fe_share={float(fe_share):.2f} | "
            f"dynamic_trim_usd=skip"
        )
        return
    print(
        f"{_DERISK_LOG_PREFIX} | evaluate | fe_share={float(fe_share):.2f} | "
        f"dynamic_trim_usd={float(dynamic_trim_usd):.2f}"
    )
