"""Per-asset cooldown persistence across cron cycles (bot_state.json)."""

from __future__ import annotations

import time

import pytest

import modules.runtime as rt


def test_asset_cooldown_persists_across_load_state(tmp_path, monkeypatch):
    path = tmp_path / "bot_state.json"
    monkeypatch.setattr(rt, "STATE_FILE", str(path))
    rt.ASSET_LAST_TRADE.clear()

    rt.mark_asset_traded("LINK_ALPHA", now=1_000.0, cooldown_seconds=1200)
    rt.save_state({"last_run": 0}, path=str(path))

    rt.ASSET_LAST_TRADE.clear()
    assert rt.can_trade_asset("LINK_ALPHA", now=1_500.0, cooldown_seconds=1200)

    rt.load_state(path=str(path))
    assert not rt.can_trade_asset("LINK_ALPHA", now=1_500.0, cooldown_seconds=1200)
    assert rt.asset_cooldown_remaining_seconds(
        "LINK_ALPHA", now=1_500.0, cooldown_seconds=1200
    ) == pytest.approx(700.0)


def test_asset_cooldown_remaining_zero_when_ready():
    rt.ASSET_LAST_TRADE["WETH_ALPHA"] = time.time() - 10_000
    assert rt.can_trade_asset("WETH_ALPHA", cooldown_seconds=1200)
    assert rt.asset_cooldown_remaining_seconds("WETH_ALPHA", cooldown_seconds=1200) == 0.0
