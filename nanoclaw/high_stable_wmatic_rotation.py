"""High-stable WMATIC rotation — capped USDC→WMATIC when stables ample and FE share moderate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import config as cfg

if TYPE_CHECKING:
    from modules.swap_executor import Balances, TradeDecision

_LOG_PREFIX = "[nanoclaw] HIGH STABLE WMATIC ROTATION"


@dataclass(frozen=True)
class HighStableWmaticContext:
    stable_usd: float
    fe_share: float
    wmatic_signal: float
    max_notional_usd: float


def _enabled() -> bool:
    return bool(getattr(cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_ROTATION_ENABLED", False))


def _min_stable_usd() -> float:
    return float(getattr(cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_STABLE_USD", 30.0))


def _max_notional_usd() -> float:
    return float(getattr(cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_NOTIONAL_USD", 10.0))


def _min_signal() -> float:
    return float(getattr(cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_SIGNAL", 0.85))


def _max_fe_share() -> float:
    return float(getattr(cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_FE_SHARE", 0.80))


def resolve_wmatic_alpha_signal() -> float:
    """WMATIC_ALPHA signal from followed_equities.json (0.0 when missing)."""
    try:
        from clean_swap import X_SIGNAL_EQUITY_TRADER

        for asset in X_SIGNAL_EQUITY_TRADER.load_followed_equities():
            if str(getattr(asset, "symbol", "")).strip().upper() == "WMATIC_ALPHA":
                raw = getattr(asset, "signal_strength", 0.0)
                return float(raw) if raw is not None else 0.0
    except Exception:
        return 0.0
    return 0.0


def _reserve_headroom_min_stables(balances: Any) -> float:
    from modules import swap_executor as se

    headroom = float(getattr(cfg, "FE_STABLE_RUNWAY_TIERED_RESERVE_HEADROOM_USD", 2.0))
    return max(0.0, se._operating_reserve_floor_usd(balances) + max(0.0, headroom))


def resolve_high_stable_wmatic_context(
    balances: Any,
    *,
    wmatic_signal: float | None = None,
    entries_paused: bool = False,
) -> HighStableWmaticContext | None:
    if not _enabled() or entries_paused:
        return None
    from nanoclaw import fe_tiered_cooldown as ftc

    stable_usd = float(balances.usdt) + float(balances.usdc)
    if ftc.cooldown_active():
        return None
    if stable_usd + 1e-9 < _min_stable_usd():
        return None
    total = float(balances.total_portfolio_usd)
    fe_usd = float(balances.followed_equity_usd)
    fe_share = (fe_usd / total) if total > 0.0 else 0.0
    if fe_share + 1e-9 >= _max_fe_share():
        return None
    sig = float(wmatic_signal if wmatic_signal is not None else resolve_wmatic_alpha_signal())
    if sig + 1e-9 < _min_signal():
        return None
    min_after = _reserve_headroom_min_stables(balances)
    max_spend = max(0.0, stable_usd - min_after)
    cap = min(_max_notional_usd(), max_spend, float(balances.usdc))
    min_trade = float(getattr(cfg, "MIN_TRADE_USD", 10.0))
    if cap + 1e-9 < min_trade:
        return None
    from nanoclaw import drawdown_throttle as dt

    cap = dt.apply_tiered_max_throttle(cap, current_total=total)
    if cap + 1e-9 < min_trade:
        return None
    return HighStableWmaticContext(
        stable_usd=stable_usd,
        fe_share=fe_share,
        wmatic_signal=sig,
        max_notional_usd=float(cap),
    )


def log_high_stable_wmatic_allow(ctx: HighStableWmaticContext) -> None:
    print(
        f"{_LOG_PREFIX} | stable_usd={ctx.stable_usd:.2f} | fe_share={ctx.fe_share:.2f} | "
        f"signal={ctx.wmatic_signal:.2f} | max_notional=${ctx.max_notional_usd:.2f}"
    )


def try_high_stable_wmatic_rotation_decision(
    balances: Any,
    *,
    wmatic_signal: float | None = None,
    entries_paused: bool = False,
) -> TradeDecision | None:
    ctx = resolve_high_stable_wmatic_context(
        balances,
        wmatic_signal=wmatic_signal,
        entries_paused=entries_paused,
    )
    if ctx is None:
        return None
    log_high_stable_wmatic_allow(ctx)
    notional = float(ctx.max_notional_usd)
    from modules.swap_executor import TradeDecision

    return TradeDecision(
        direction="USDC_TO_WMATIC",
        amount_in=int(notional * 1_000_000),
        trade_size=notional,
        message=(
            f"🟦 HIGH STABLE WMATIC ROTATION | USDC→WMATIC ${notional:.2f} | "
            f"signal={ctx.wmatic_signal:.2f} | stables=${ctx.stable_usd:.2f}"
        ),
        signal_strength=float(ctx.wmatic_signal),
    )
