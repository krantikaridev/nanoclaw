"""External risk / defensive-clamp policy loaded from environment (``.env``)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")

_CLAMP_LOG_PREFIX = "[EXTERNAL][DEFENSIVE_CLAMP]"


def _env_raw(key: str) -> str | None:
    val = os.getenv(key)
    if val is None:
        return None
    stripped = val.strip()
    return stripped if stripped else None


def _env_float(
    key: str,
    default: float,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
) -> float:
    raw = _env_raw(key)
    if raw is None:
        out = float(default)
    else:
        try:
            out = float(raw)
        except ValueError:
            out = float(default)
        if out != out:  # NaN
            out = float(default)
    if min_val is not None:
        out = max(min_val, out)
    if max_val is not None:
        out = min(max_val, out)
    return out


def _env_int(key: str, default: int, *, min_val: int = 1, max_val: int = 100) -> int:
    raw = _env_raw(key)
    if raw is None:
        out = int(default)
    else:
        try:
            out = int(float(raw))
        except ValueError:
            out = int(default)
    return max(min_val, min(max_val, out))


@dataclass(frozen=True)
class RiskTierPolicy:
    """Balance tier thresholds (stable runway + WMATIC gas runway)."""

    critical_stable_usd: float = 60.0
    critical_wmatic: float = 50.0
    moderate_stable_usd: float = 100.0
    moderate_wmatic: float = 65.0
    critical_wmatic_when_stable_ok: float = 10.0
    travel_stable_usd: float = 95.0
    travel_min_copy_pct: float = 0.045
    tier_critical_copy_pct: float = 0.02
    tier_moderate_copy_pct: float = 0.03
    tier_healthy_copy_pct: float = 0.06


@dataclass(frozen=True)
class ClampPolicy:
    """Defensive streak clamp (in-memory timer in ``risk_checker``)."""

    streak_evals: int = 3
    duration_sec: float = 600.0
    deque_maxlen: int = 5
    arm_max_stable_usd: float = 95.0
    recovery_stable_usd: float = 95.0
    healthy_stable_usd: float = 100.0
    recovery_wmatic: float = 65.0
    streak_floor_pct: float = 0.02
    travel_floor_pct: float = 0.045
    min_copy_pct: float = 0.02
    max_copy_pct: float = 0.10


@dataclass(frozen=True)
class ExternalRiskPolicy:
    tier: RiskTierPolicy
    clamp: ClampPolicy


_policy: ExternalRiskPolicy | None = None
_policy_logged: bool = False


def load_risk_policy() -> ExternalRiskPolicy:
    """Build policy from ``EXTERNAL_RISK_*`` / ``EXTERNAL_CLAMP_*`` env vars."""
    tier = RiskTierPolicy(
        critical_stable_usd=_env_float("EXTERNAL_RISK_CRITICAL_STABLE_USD", 60.0, min_val=0.0),
        critical_wmatic=_env_float("EXTERNAL_RISK_CRITICAL_WMATIC", 50.0, min_val=0.0),
        moderate_stable_usd=_env_float("EXTERNAL_RISK_MODERATE_STABLE_USD", 100.0, min_val=1.0),
        moderate_wmatic=_env_float("EXTERNAL_RISK_MODERATE_WMATIC", 65.0, min_val=0.0),
        critical_wmatic_when_stable_ok=_env_float(
            "EXTERNAL_RISK_CRITICAL_WMATIC_WHEN_STABLE_OK", 10.0, min_val=0.0
        ),
        travel_stable_usd=_env_float("EXTERNAL_RISK_TRAVEL_STABLE_USD", 95.0, min_val=0.0),
        travel_min_copy_pct=_env_float(
            "EXTERNAL_RISK_TRAVEL_MIN_COPY_PCT", 0.045, min_val=0.01, max_val=0.10
        ),
        tier_critical_copy_pct=_env_float(
            "EXTERNAL_RISK_TIER_CRITICAL_COPY_PCT", 0.02, min_val=0.01, max_val=0.10
        ),
        tier_moderate_copy_pct=_env_float(
            "EXTERNAL_RISK_TIER_MODERATE_COPY_PCT", 0.03, min_val=0.01, max_val=0.10
        ),
        tier_healthy_copy_pct=_env_float(
            "EXTERNAL_RISK_TIER_HEALTHY_COPY_PCT", 0.06, min_val=0.01, max_val=0.10
        ),
    )
    streak_evals = _env_int("EXTERNAL_CLAMP_STREAK_EVALS", 3, min_val=1, max_val=10)
    clamp = ClampPolicy(
        streak_evals=streak_evals,
        duration_sec=_env_float("EXTERNAL_CLAMP_DURATION_SEC", 600.0, min_val=30.0),
        deque_maxlen=_env_int(
            "EXTERNAL_CLAMP_DEQUE_MAXLEN",
            max(5, streak_evals + 2),
            min_val=streak_evals,
            max_val=20,
        ),
        arm_max_stable_usd=_env_float(
            "EXTERNAL_CLAMP_ARM_MAX_STABLE_USD", tier.travel_stable_usd, min_val=0.0
        ),
        recovery_stable_usd=_env_float(
            "EXTERNAL_CLAMP_RECOVERY_STABLE_USD", tier.travel_stable_usd, min_val=0.0
        ),
        healthy_stable_usd=_env_float(
            "EXTERNAL_CLAMP_HEALTHY_STABLE_USD", tier.moderate_stable_usd, min_val=1.0
        ),
        recovery_wmatic=_env_float("EXTERNAL_CLAMP_RECOVERY_WMATIC", 65.0, min_val=0.0),
        streak_floor_pct=_env_float(
            "EXTERNAL_CLAMP_STREAK_FLOOR_PCT", 0.02, min_val=0.01, max_val=0.10
        ),
        travel_floor_pct=_env_float(
            "EXTERNAL_CLAMP_TRAVEL_FLOOR_PCT", 0.045, min_val=0.01, max_val=0.10
        ),
        min_copy_pct=_env_float("EXTERNAL_CLAMP_MIN_COPY_PCT", 0.02, min_val=0.01, max_val=0.10),
        max_copy_pct=_env_float("EXTERNAL_CLAMP_MAX_COPY_PCT", 0.10, min_val=0.02, max_val=0.25),
    )
    return ExternalRiskPolicy(tier=tier, clamp=clamp)


def get_risk_policy() -> ExternalRiskPolicy:
    """Cached policy for the external-layer process."""
    global _policy
    if _policy is None:
        _policy = load_risk_policy()
    return _policy


def reload_risk_policy_for_tests() -> ExternalRiskPolicy:
    """Force reload (unit tests after ``monkeypatch.setenv``)."""
    global _policy, _policy_logged
    _policy = load_risk_policy()
    _policy_logged = False
    return _policy


def log_risk_policy_once() -> None:
    """Emit loaded thresholds once per process (external layer startup)."""
    global _policy_logged
    if _policy_logged:
        return
    _policy_logged = True
    p = get_risk_policy()
    t = p.tier
    c = p.clamp
    print(
        "[EXTERNAL] risk_policy | "
        f"critical_stable_usd={t.critical_stable_usd:.0f} "
        f"moderate_stable_usd={t.moderate_stable_usd:.0f} "
        f"travel_stable_usd={t.travel_stable_usd:.0f} "
        f"moderate_wmatic={t.moderate_wmatic:.0f} | "
        f"clamp_streak_evals={c.streak_evals} "
        f"clamp_duration_sec={c.duration_sec:.0f} "
        f"recovery_stable_usd={c.recovery_stable_usd:.0f} "
        f"healthy_stable_usd={c.healthy_stable_usd:.0f}",
        flush=True,
    )


def clamp_log_prefix() -> str:
    return _CLAMP_LOG_PREFIX
