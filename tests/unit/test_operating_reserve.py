"""Operating reserve floor — defer new entries when stables below seed × pct."""

from __future__ import annotations

import pytest

from modules import swap_executor as se


class _Bal:
    def __init__(
        self,
        *,
        usdt: float = 0.0,
        usdc: float = 0.0,
        total: float = 122.0,
        fe: float = 111.0,
        wmatic: float = 0.0,
        pol: float = 14.0,
    ) -> None:
        self.usdt = usdt
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = fe
        self.wmatic = wmatic
        self.pol = pol


def test_operating_reserve_blocks_when_stables_below_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 132.0)
    bal = _Bal(usdc=8.91, total=121.93, fe=111.55)
    ctx = se._operating_reserve_buy_block_context(bal)  # noqa: SLF001
    assert ctx is not None
    assert ctx["reserve_floor_usd"] == pytest.approx(13.2)
    assert ctx["stable_usd"] == pytest.approx(8.91)
    assert se._operating_reserve_buy_block_active(bal) is True  # noqa: SLF001


def test_operating_reserve_passes_when_stables_above_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 132.0)
    bal = _Bal(usdc=17.91, total=131.55)
    assert se._operating_reserve_buy_block_context(bal) is None  # noqa: SLF001


def test_operating_reserve_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", False)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 132.0)
    bal = _Bal(usdc=1.0)
    assert se._operating_reserve_buy_block_context(bal) is None  # noqa: SLF001


def test_operating_reserve_uses_total_when_seed_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 0.0)
    bal = _Bal(usdc=10.0, total=100.0)
    ctx = se._operating_reserve_buy_block_context(bal)  # noqa: SLF001
    assert ctx is None  # floor=10, stable=10
