"""High-FE de-risk trim in stables dead zone ($15–$40, WMATIC dust)."""

from __future__ import annotations

import pytest

from modules import swap_executor as se
from modules import signal as signal_module


class _Bal:
    def __init__(
        self,
        *,
        usdt: float = 1.07,
        usdc: float = 18.04,
        total: float = 154.21,
        fe: float = 128.34,
        wmatic: float = 60.488332,
    ) -> None:
        self.usdt = usdt
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = fe
        self.wmatic = wmatic
        self.pol = 11.0


def _patch_stage_vm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MIN_FE_SHARE", 0.80)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MIN_STABLE_USD", 15.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MAX_TRIM_NOTIONAL_USD", 12.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_MAX_WMATIC_USD", 8.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED", False)
    monkeypatch.setattr(se.cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD", 15.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 158.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_AUTO_SYNC_ENABLED", False)


def test_derisk_context_matches_stage_vm_book(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    bal = _Bal()
    assert se._fe_stable_runway_context(bal, wmatic_usd=5.53) is None  # noqa: SLF001
    ctx = se._fe_stable_runway_derisk_context(bal, wmatic_usd=5.53)  # noqa: SLF001
    assert ctx is not None
    assert ctx["stable_usd"] == pytest.approx(19.11)
    assert ctx["fe_share"] == pytest.approx(128.34 / 154.21, rel=1e-3)
    assert ctx["max_trim_usd"] == pytest.approx(12.0)


def test_derisk_blocks_when_wmatic_rebuild_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    bal = _Bal(usdc=19.0, fe=127.0, total=155.0)
    assert se._fe_stable_runway_derisk_context(bal, wmatic_usd=10.0) is None  # noqa: SLF001


def test_derisk_blocks_low_fe_share(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    bal = _Bal(fe=70.0, total=154.0)
    assert se._fe_stable_runway_derisk_context(bal, wmatic_usd=5.0) is None  # noqa: SLF001


def test_derisk_blocks_critical_stables_band(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    bal = _Bal(usdt=1.0, usdc=13.0, total=150.0, fe=120.0, wmatic=0.0)
    assert se._fe_stable_runway_derisk_context(bal, wmatic_usd=0.0) is None  # noqa: SLF001
    assert se._fe_stable_runway_context(bal, wmatic_usd=0.0) is not None  # noqa: SLF001


def test_derisk_sell_fraction_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(signal_module.cfg, "MIN_TRADE_USD", 10.0)
    frac = signal_module._fe_stable_runway_derisk_compute_sell_fraction(
        position_usd=128.0,
        max_trim_usd=12.0,
    )
    assert frac == pytest.approx(12.0 / 128.0)
