"""Periodic on-chain PnL flow sync from external_layer (non-blocking)."""

from __future__ import annotations

import os
import time

_last_sync_unix: float = 0.0


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


def pnl_flow_auto_sync_enabled() -> bool:
    return _env_bool("PNL_FLOW_AUTO_SYNC_ENABLED", False)


def reset_pnl_flow_gate_state_for_tests() -> None:
    global _last_sync_unix
    _last_sync_unix = 0.0


def maybe_run_pnl_flow_sync(*, now_unix: float | None = None, **sync_kwargs: object) -> None:
    """Run on-chain flow sync on interval; log scraped/appended counts."""
    if not pnl_flow_auto_sync_enabled():
        return

    from nanoclaw.opex_runway import format_wallet_short
    from nanoclaw.pnl_flow_onchain import pnl_flow_onchain_enabled, run_pnl_flow_sync

    if not pnl_flow_onchain_enabled():
        return

    global _last_sync_unix
    now = time.time() if now_unix is None else float(now_unix)
    interval_h = max(_env_float("PNL_FLOW_AUTO_SYNC_INTERVAL_HOURS", 6.0), 0.25)
    interval_s = interval_h * 3600.0
    if _last_sync_unix > 0 and (now - _last_sync_unix) < interval_s:
        return
    _last_sync_unix = now

    result = run_pnl_flow_sync(**sync_kwargs)
    if result is None:
        return

    wallet_short = format_wallet_short(result.wallet)
    print(
        f"[nanoclaw] PNL_FLOW_SYNC | scraped={result.scraped} appended={result.appended} "
        f"wallet={wallet_short}",
        flush=True,
    )
