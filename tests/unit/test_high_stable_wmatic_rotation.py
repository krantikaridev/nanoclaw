"""High-stable WMATIC rotation (Agent S)."""

from __future__ import annotations

import pytest

from nanoclaw import high_stable_wmatic_rotation as hswm


class _Bal:
    def __init__(
        self,
        *,
        usdt: float = 1.07,
        usdc: float = 30.0,
        total: float = 154.25,
        fe: float = 116.22,
        wmatic: float = 60.0,
    ) -> None:
        self.usdt = usdt
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = fe
        self.wmatic = wmatic
        self.pol = 11.0


def _patch_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hswm.cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_ROTATION_ENABLED", True)
    monkeypatch.setattr(hswm.cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_STABLE_USD", 30.0)
    monkeypatch.setattr(hswm.cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_NOTIONAL_USD", 10.0)
    monkeypatch.setattr(hswm.cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_SIGNAL", 0.85)
    monkeypatch.setattr(hswm.cfg, "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_FE_SHARE", 0.80)
    monkeypatch.setattr(hswm.cfg, "STAGE_SEED_USD", 158.0)
    monkeypatch.setattr(hswm.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(hswm.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(hswm.cfg, "FE_STABLE_RUNWAY_TIERED_RESERVE_HEADROOM_USD", 2.0)
    monkeypatch.setattr(hswm.cfg, "MIN_TRADE_USD", 10.0)
    monkeypatch.setattr(hswm.cfg, "DRAWDOWN_THROTTLE_ENABLED", False)


def test_eligible_post_derisk_book(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    from nanoclaw import fe_tiered_cooldown as ftc

    monkeypatch.setattr(ftc, "cooldown_active", lambda **kwargs: False)
    bal = _Bal()
    ctx = hswm.resolve_high_stable_wmatic_context(bal, wmatic_signal=0.92)
    assert ctx is not None
    assert ctx.max_notional_usd == pytest.approx(10.0)


def test_blocks_high_fe_share(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    from nanoclaw import fe_tiered_cooldown as ftc

    monkeypatch.setattr(ftc, "cooldown_active", lambda **kwargs: False)
    bal = _Bal(fe=128.0, total=154.0)
    assert hswm.resolve_high_stable_wmatic_context(bal, wmatic_signal=0.92) is None


def test_blocks_when_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    bal = _Bal()
    assert hswm.resolve_high_stable_wmatic_context(bal, wmatic_signal=0.92, entries_paused=True) is None


def test_builds_usdc_to_wmatic_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    from nanoclaw import fe_tiered_cooldown as ftc

    monkeypatch.setattr(ftc, "cooldown_active", lambda **kwargs: False)
    decision = hswm.try_high_stable_wmatic_rotation_decision(_Bal(), wmatic_signal=0.92)
    assert decision is not None
    assert decision.direction == "USDC_TO_WMATIC"
    assert decision.trade_size == pytest.approx(10.0)
