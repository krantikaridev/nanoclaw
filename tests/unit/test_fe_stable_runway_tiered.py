"""Tiered FE stable runway — capped X-SIGNAL BUY below full runway target."""

from __future__ import annotations

import pytest

from modules import swap_executor as se


class _Bal:
    def __init__(
        self,
        *,
        usdt: float = 0.0,
        usdc: float = 0.0,
        total: float = 140.0,
        fe: float = 111.0,
    ) -> None:
        self.usdt = usdt
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = fe
        self.wmatic = 0.0
        self.pol = 14.0


def test_tiered_bypass_matches_vm_book(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL", 0.85)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 132.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)

    bal = _Bal(usdt=0.93, usdc=26.53, total=140.0, fe=111.0)
    assert se._fe_stable_runway_buy_block_active(bal) is True  # noqa: SLF001
    ctx = se._fe_stable_runway_tiered_bypass_context(bal, signal_strength=0.87)  # noqa: SLF001
    assert ctx is not None
    assert ctx["max_notional_usd"] == pytest.approx(10.0)
    capped = se.fe_stable_runway_tiered_cap_notional_usd(bal, signal_strength=0.87, proposed_notional_usd=12.0)
    assert capped == pytest.approx(10.0)


def test_tiered_blocks_weak_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL", 0.85)
    bal = _Bal(usdc=27.0, total=140.0, fe=111.0)
    assert se._fe_stable_runway_tiered_bypass_context(bal, signal_strength=0.80) is None  # noqa: SLF001


def test_tiered_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_ENABLED", False)
    bal = _Bal(usdc=27.0, total=140.0, fe=111.0)
    assert se._fe_stable_runway_tiered_bypass_context(bal, signal_strength=0.90) is None  # noqa: SLF001


def test_tiered_exempt_below_operating_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage VM Jun 2026: stables $14.49 < reserve $15.80 — tiered still allowed."""
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL", 0.85)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_TIERED_EXEMPT_ENABLED", True)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 158.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_AUTO_SYNC_ENABLED", False)

    bal = _Bal(usdt=1.07, usdc=13.42, total=158.16, fe=131.5)
    assert se._operating_reserve_buy_block_active(bal) is True  # noqa: SLF001
    ctx = se._fe_stable_runway_tiered_bypass_context(bal, signal_strength=0.92)  # noqa: SLF001
    assert ctx is not None
    capped = se.fe_stable_runway_tiered_cap_notional_usd(bal, signal_strength=0.92, proposed_notional_usd=12.0)
    assert capped == pytest.approx(10.0)
