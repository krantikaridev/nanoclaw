"""Unit tests for nanoclaw.fe_dynamic_trim."""

from __future__ import annotations

import pytest

from nanoclaw import fe_dynamic_trim as fdt
from modules import swap_executor as se


def _patch_dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fdt.cfg, "FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED", True)
    monkeypatch.setattr(fdt.cfg, "FE_STABLE_RUNWAY_DERISK_LOW_FE_SHARE", 0.70)
    monkeypatch.setattr(fdt.cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_SHARE", 0.85)
    monkeypatch.setattr(fdt.cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_MAX_TRIM_USD", 15.0)


def test_high_fe_share_uses_high_max_trim(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dynamic(monkeypatch)
    out = fdt.resolve_derisk_dynamic_trim(
        0.87,
        default_max_trim_usd=12.0,
        default_min_fe_share=0.80,
    )
    assert out.max_trim_usd == pytest.approx(15.0)
    assert out.dynamic_trim_usd == pytest.approx(15.0)
    assert out.min_fe_share == pytest.approx(0.70)


def test_72_fe_share_resolves_default_trim_with_static_min_fe(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dynamic(monkeypatch)
    out = fdt.resolve_derisk_dynamic_trim(
        0.72,
        default_max_trim_usd=12.0,
        default_min_fe_share=0.80,
    )
    assert out.max_trim_usd == pytest.approx(12.0)
    assert out.dynamic_trim_usd == pytest.approx(12.0)
    assert out.min_fe_share == pytest.approx(0.80)


def test_mid_fe_share_uses_default_max_trim(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dynamic(monkeypatch)
    out = fdt.resolve_derisk_dynamic_trim(
        0.75,
        default_max_trim_usd=12.0,
        default_min_fe_share=0.80,
    )
    assert out.max_trim_usd == pytest.approx(12.0)
    assert out.dynamic_trim_usd == pytest.approx(12.0)
    assert out.min_fe_share == pytest.approx(0.80)


def test_below_low_fe_share_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_dynamic(monkeypatch)
    out = fdt.resolve_derisk_dynamic_trim(
        0.68,
        default_max_trim_usd=12.0,
        default_min_fe_share=0.80,
    )
    assert out.max_trim_usd is None
    assert out.dynamic_trim_usd is None


def test_dynamic_disabled_uses_static_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fdt.cfg, "FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED", False)
    out = fdt.resolve_derisk_dynamic_trim(
        0.87,
        default_max_trim_usd=12.0,
        default_min_fe_share=0.80,
    )
    assert out.max_trim_usd == pytest.approx(12.0)
    assert out.dynamic_trim_usd is None
    assert out.min_fe_share == pytest.approx(0.80)


def test_log_dynamic_trim_includes_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_dynamic(monkeypatch)
    fdt.log_dynamic_trim(fe_share=0.87, dynamic_trim_usd=15.0)
    out = capsys.readouterr().out
    assert "DERISK | evaluate" in out
    assert "dynamic_trim_usd=15.00" in out


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
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_LOW_FE_SHARE", 0.70)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_SHARE", 0.85)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_DERISK_HIGH_FE_MAX_TRIM_USD", 15.0)
    monkeypatch.setattr(se.cfg, "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD", 15.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 158.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_AUTO_SYNC_ENABLED", False)


def test_derisk_context_off_at_72_fe_share(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    bal = _Bal(fe=110.88, total=154.0)
    assert se._fe_stable_runway_derisk_context(bal, wmatic_usd=5.0) is None  # noqa: SLF001


def test_derisk_context_default_trim_at_81_fe_share(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    bal = _Bal(fe=124.71, total=154.0)
    ctx = se._fe_stable_runway_derisk_context(bal, wmatic_usd=5.53)  # noqa: SLF001
    assert ctx is not None
    assert ctx["max_trim_usd"] == pytest.approx(12.0)
    assert ctx["dynamic_trim_usd"] == pytest.approx(12.0)


def test_derisk_context_high_trim_at_87_fe_share(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    bal = _Bal(fe=134.07, total=154.0)
    ctx = se._fe_stable_runway_derisk_context(bal, wmatic_usd=5.53)  # noqa: SLF001
    assert ctx is not None
    assert ctx["max_trim_usd"] == pytest.approx(15.0)
    assert ctx["dynamic_trim_usd"] == pytest.approx(15.0)


def test_derisk_dead_zone_bounds_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stage_vm(monkeypatch)
    critical = _Bal(usdt=1.0, usdc=13.0, total=150.0, fe=120.0, wmatic=0.0)
    assert se._fe_stable_runway_derisk_context(critical, wmatic_usd=0.0) is None  # noqa: SLF001
    assert se._fe_stable_runway_context(critical, wmatic_usd=0.0) is not None  # noqa: SLF001

    stage = _Bal()
    assert se._fe_stable_runway_context(stage, wmatic_usd=5.53) is None  # noqa: SLF001
    ctx = se._fe_stable_runway_derisk_context(stage, wmatic_usd=5.53)  # noqa: SLF001
    assert ctx is not None
    assert ctx["stable_usd"] == pytest.approx(19.11)
