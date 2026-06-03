"""Unit tests for nanoclaw.window_stress_derisk."""

from __future__ import annotations

import pytest

from external_layer.control import CycleControlSnapshot
from nanoclaw import window_stress_derisk as wsd
from modules import swap_executor as se


def test_is_window_pnl_pause_reason_matches_auto_pause_format() -> None:
    assert wsd.is_window_pnl_pause_reason("auto_pause | window PnL below -2.0% over 12h")
    assert not wsd.is_window_pnl_pause_reason("auto_pause | session below -1.0% floor")
    assert not wsd.is_window_pnl_pause_reason("auto_unpause | window=12h")
    assert not wsd.is_window_pnl_pause_reason(None)


def test_resolve_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsd.cfg, "WINDOW_STRESS_DERISK_ENABLED", False)
    out = wsd.resolve_window_stress_derisk(
        paused=True,
        reason="auto_pause | window PnL below -2.0% over 12h",
    )
    assert out is None


def test_resolve_returns_overrides_when_window_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsd.cfg, "WINDOW_STRESS_DERISK_ENABLED", True)
    monkeypatch.setattr(wsd.cfg, "WINDOW_STRESS_DERISK_MIN_FE_SHARE", 0.72)
    monkeypatch.setattr(wsd.cfg, "WINDOW_STRESS_DERISK_MAX_WMATIC_USD", 12.0)
    out = wsd.resolve_window_stress_derisk(
        paused=True,
        reason="auto_pause | window PnL below -2.0% over 12h",
    )
    assert out is not None
    assert out.min_fe_share == pytest.approx(0.72)
    assert out.max_wmatic_usd == pytest.approx(12.0)


def test_resolve_blocks_session_pause_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsd.cfg, "WINDOW_STRESS_DERISK_ENABLED", True)
    out = wsd.resolve_window_stress_derisk(
        paused=True,
        reason="auto_pause | session below -1.0% floor",
    )
    assert out is None


class _Bal:
    def __init__(
        self,
        *,
        usdt: float = 1.07,
        usdc: float = 25.0,
        total: float = 146.0,
        fe: float = 108.0,
        wmatic: float = 60.488332,
    ) -> None:
        self.usdt = usdt
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = fe
        self.wmatic = wmatic
        self.pol = 11.0


def _patch_stage_vm(
    monkeypatch: pytest.MonkeyPatch,
    *,
    window_stress_enabled: bool,
    pause_reason: str,
) -> None:
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MIN_FE_SHARE", 0.80)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MIN_STABLE_USD", 15.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MAX_TRIM_NOTIONAL_USD", 12.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MAX_WMATIC_USD", 8.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_LOW_FE_SHARE", 0.70)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_SHARE", 0.85)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_MAX_TRIM_USD", 15.0)
    monkeypatch.setattr(se.cfg, "WINDOW_STRESS_DERISK_ENABLED", window_stress_enabled)
    monkeypatch.setattr(se.cfg, "WINDOW_STRESS_DERISK_MIN_FE_SHARE", 0.72)
    monkeypatch.setattr(se.cfg, "WINDOW_STRESS_DERISK_MAX_WMATIC_USD", 12.0)
    monkeypatch.setattr(se.cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD", 15.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 158.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_AUTO_SYNC_ENABLED", False)
    monkeypatch.setattr(
        "external_layer.control.load_cycle_control",
        lambda path=None: CycleControlSnapshot(paused=True, reason=pause_reason),
    )


def test_window_stress_derisk_context_relaxes_fe_and_wmatic_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage VM book: ~74% FE, ~$26 stables, WMATIC ~$10 — static derisk blocked, window stress allows."""
    bal = _Bal()
    _patch_stage_vm(
        monkeypatch,
        window_stress_enabled=False,
        pause_reason="auto_pause | window PnL below -2.0% over 12h",
    )
    assert se._fe_stable_runway_derisk_context(bal, wmatic_usd=10.0) is None  # noqa: SLF001

    _patch_stage_vm(
        monkeypatch,
        window_stress_enabled=True,
        pause_reason="auto_pause | window PnL below -2.0% over 12h",
    )
    ctx = se._fe_stable_runway_derisk_context(bal, wmatic_usd=10.0)  # noqa: SLF001
    assert ctx is not None
    assert ctx["fe_share"] == pytest.approx(108.0 / 146.0, rel=1e-3)
    assert ctx["max_trim_usd"] == pytest.approx(12.0)
    assert ctx.get("window_stress_derisk") == pytest.approx(1.0)


def test_window_stress_derisk_still_blocks_session_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(
        monkeypatch,
        window_stress_enabled=True,
        pause_reason="auto_pause | session below -1.0% floor",
    )
    bal = _Bal()
    assert se._fe_stable_runway_derisk_context(bal, wmatic_usd=10.0) is None  # noqa: SLF001
