"""Periodic opex runway check from external_layer (non-blocking alerts)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

_last_check_unix: float = 0.0
_last_ok_log_unix: float = 0.0


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


def opex_auto_check_enabled() -> bool:
    return _env_bool("OPEX_RUNWAY_AUTO_CHECK_ENABLED", True)


def reset_opex_gate_state_for_tests() -> None:
    global _last_check_unix, _last_ok_log_unix
    _last_check_unix = 0.0
    _last_ok_log_unix = 0.0


def maybe_run_opex_runway_check(*, stable_usd: float | None = None, now_unix: float | None = None) -> None:
    """Run opex runway check on interval; always log alerts, throttle OK logs."""
    if not opex_auto_check_enabled():
        return

    global _last_check_unix, _last_ok_log_unix
    now = time.time() if now_unix is None else float(now_unix)
    interval_h = max(_env_float("OPEX_RUNWAY_AUTO_CHECK_INTERVAL_HOURS", 6.0), 0.25)
    interval_s = interval_h * 3600.0
    if _last_check_unix > 0 and (now - _last_check_unix) < interval_s:
        return
    _last_check_unix = now

    from nanoclaw.opex_runway import assess_opex_runway, format_opex_runway_message, resolve_stables_usd

    resolved = resolve_stables_usd(override=stable_usd)
    if resolved is None:
        print(
            f"[EXTERNAL] opex_runway | {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} | "
            "stables unavailable — skip"
        )
        return

    assessment = assess_opex_runway(resolved)
    if assessment.monthly_total_usd <= 0.0:
        return

    if assessment.alert_active:
        print(f"[EXTERNAL] {format_opex_runway_message(assessment)}")
        telegram_enabled = _env_bool("OPEX_RUNWAY_TELEGRAM_ENABLED", False)
        if telegram_enabled:
            try:
                from nanoclaw.opex_runway import format_opex_runway_telegram
                from modules.agent_layer import _telegram_send_html

                _telegram_send_html(format_opex_runway_telegram(assessment))
            except Exception:
                pass
        return

    ok_interval_s = max(interval_s, 3600.0)
    if _last_ok_log_unix > 0 and (now - _last_ok_log_unix) < ok_interval_s:
        return
    _last_ok_log_unix = now
    tail = format_opex_runway_message(assessment).split(" | ", 1)[-1]
    print(f"[EXTERNAL] opex_runway OK | {tail}")
