"""RPC endpoint health gate for external_layer → control.json auto pause."""

from __future__ import annotations

import os
from pathlib import Path

from nanoclaw.runtime_state import OPERATOR_PAUSE_LOCK_KEY

_REPO_ROOT = Path(__file__).resolve().parent.parent

RPC_PAUSE_REASON = "auto_pause | RPC all endpoints failed"
_RPC_FAIL_STREAK_THRESHOLD = 2

_rpc_all_fail_streak: int = 0
_rpc_paused: bool = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        try:
            import config as cfg

            return bool(getattr(cfg, name, default))
        except Exception:
            return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def rpc_pause_enabled() -> bool:
    return _env_bool("EXTERNAL_RPC_PAUSE_ENABLED", False)


def reset_rpc_gate_state_for_tests() -> None:
    """Clear module streak / RPC-pause latch (unit tests)."""
    global _rpc_all_fail_streak, _rpc_paused
    _rpc_all_fail_streak = 0
    _rpc_paused = False


def _is_rpc_pause_reason(reason: object) -> bool:
    return isinstance(reason, str) and reason.strip() == RPC_PAUSE_REASON


def _sync_rpc_paused_from_payload(payload: dict[str, object]) -> None:
    global _rpc_paused
    if _rpc_paused:
        return
    if payload.get("rpc_pause_control") is True:
        _rpc_paused = True
        return
    if _is_rpc_pause_reason(payload.get("reason")):
        _rpc_paused = True


def _evaluate_green_unpause() -> tuple[bool, str, tuple[str, ...]]:
    try:
        from .auto_pause import evaluate_auto_pause
    except ImportError:
        from auto_pause import evaluate_auto_pause  # type: ignore[no-redef]
    return evaluate_auto_pause()


def apply_rpc_pause_control(payload: dict[str, object]) -> dict[str, object]:
    """When enabled, pause after consecutive all-endpoint probe failures; unpause via green gates."""
    if not rpc_pause_enabled():
        return payload

    from nanoclaw.rpc_probe import any_endpoint_healthy, probe_configured_endpoints

    global _rpc_all_fail_streak, _rpc_paused

    _sync_rpc_paused_from_payload(payload)
    merged = dict(payload)
    probes = probe_configured_endpoints()
    healthy = any_endpoint_healthy(probes)

    if not healthy:
        _rpc_all_fail_streak += 1
        if _rpc_all_fail_streak >= _RPC_FAIL_STREAK_THRESHOLD:
            _rpc_paused = True
            merged["paused"] = True
            merged["reason"] = RPC_PAUSE_REASON
            merged["rpc_pause_control"] = True
            merged[OPERATOR_PAUSE_LOCK_KEY] = False
        return merged

    _rpc_all_fail_streak = 0
    if not _rpc_paused:
        return merged

    allowed, reason, rotation = _evaluate_green_unpause()
    merged["rpc_pause_control"] = True
    merged[OPERATOR_PAUSE_LOCK_KEY] = False
    if allowed:
        _rpc_paused = False
        merged["paused"] = False
        merged["reason"] = reason
        if rotation:
            merged["rotation_open"] = list(rotation)
    else:
        merged["paused"] = True
        merged["reason"] = reason
    return merged
