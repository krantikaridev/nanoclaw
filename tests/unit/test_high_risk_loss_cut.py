"""HIGH-risk X-SIGNAL loss-cut (underwater trim + BUY block)."""

from __future__ import annotations

import pytest

import config as cfg
from modules import x_signal_position as xsp
from modules.signal import (
    _max_eligible_buy_signal_strength_for_reduced_high,
    _try_build_high_risk_loss_cut_decision,
)
from nanoclaw.strategies.signal_equity_trader import FollowedEquity, SignalEquityTrader, SignalEquityTraderConfig
from modules.runtime import Balances


def test_underwater_detected_when_spot_below_entry_threshold():
    state = {
        "x_signal_equity_entries": {
            "LINK_ALPHA": {"entry_price_usd": 10.0, "notional_usd": 20.0},
        }
    }
    underwater, entry, spot, loss = xsp.underwater_context(
        state,
        "LINK_ALPHA",
        fallback_price_usd=9.43,
        live_spot_usd=9.0,
    )
    assert underwater
    assert entry == pytest.approx(10.0)
    assert spot == pytest.approx(9.0)
    assert loss == pytest.approx(10.0)


def test_underwater_false_when_spot_near_entry():
    state = {
        "x_signal_equity_entries": {
            "LINK_ALPHA": {"entry_price_usd": 10.0, "notional_usd": 20.0},
        }
    }
    underwater, _, _, _ = xsp.underwater_context(
        state,
        "LINK_ALPHA",
        fallback_price_usd=10.0,
        live_spot_usd=9.8,
    )
    assert not underwater


def test_record_and_resolve_entry():
    state: dict = {}
    xsp.record_equity_entry(
        state,
        "LINK_ALPHA",
        entry_price_usd=12.5,
        notional_usd=10.0,
        tx_hash="0xabc",
    )
    assert xsp.resolve_entry_price_usd(state, "LINK_ALPHA") == pytest.approx(12.5)


def test_max_buy_strength_excludes_underwater_symbol(monkeypatch):
    monkeypatch.setattr(xsp, "allow_high_risk_loss_cut_xsignal", lambda: True)
    monkeypatch.setattr(xsp, "loss_cut_symbols", lambda: frozenset({"LINK_ALPHA"}))
    link = FollowedEquity(
        symbol="LINK_ALPHA",
        token_address="0x" + "a" * 40,
        decimals=18,
        signal_strength=0.81,
        current_price_usd=9.0,
    )
    other = FollowedEquity(
        symbol="WETH_ALPHA",
        token_address="0x" + "b" * 40,
        decimals=18,
        signal_strength=0.85,
        current_price_usd=3000.0,
    )
    state = {
        "x_signal_equity_entries": {
            "LINK_ALPHA": {"entry_price_usd": 10.0, "notional_usd": 20.0},
        }
    }

    def _bal(addr: str, dec: int) -> float:
        return 12.0 if addr == link.token_address else 0.0

    mx = _max_eligible_buy_signal_strength_for_reduced_high(
        [link, other],
        state=state,
        get_equity_balance=_bal,
    )
    assert mx == pytest.approx(0.85)


def test_loss_cut_builds_sell_decision(monkeypatch):
    monkeypatch.setattr(xsp, "allow_high_risk_loss_cut_xsignal", lambda: True)
    monkeypatch.setattr(cfg, "HIGH_RISK_LOSS_CUT_MIN_PORTFOLIO_USD", 130.0, raising=False)
    monkeypatch.setattr(cfg, "HIGH_RISK_LOSS_CUT_LOSS_PCT", 3.0, raising=False)
    monkeypatch.setattr(cfg, "HIGH_RISK_LOSS_CUT_SYMBOLS", frozenset({"LINK_ALPHA"}), raising=False)

    link = FollowedEquity(
        symbol="LINK_ALPHA",
        token_address="0x" + "c" * 40,
        decimals=18,
        signal_strength=0.81,
        current_price_usd=9.0,
    )
    state = {
        "x_signal_equity_entries": {
            "LINK_ALPHA": {"entry_price_usd": 10.0, "notional_usd": 20.0},
        }
    }
    trader = SignalEquityTrader(
        config=SignalEquityTraderConfig(enabled=True),
        gas_protector=None,
        usdc_address="0x" + "d" * 40,
    )

    decision = _try_build_high_risk_loss_cut_decision(
        assets=[link],
        balances=Balances(
            usdt=0.0,
            usdc=15.0,
            wmatic=80.0,
            pol=1.0,
            total_portfolio_usd=140.0,
        ),
        risk_level="HIGH",
        state=state,
        trader=trader,
        secs_cooldown=60,
        get_token_balance=lambda _a, _d: 12.0,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert decision is not None
    assert decision.direction == "EQUITY_TO_USDC"
    assert decision.amount_in > 0
    assert "loss-cut" in str(decision.message).lower()


def test_loss_cut_disabled_by_env(monkeypatch):
    monkeypatch.setattr(xsp, "allow_high_risk_loss_cut_xsignal", lambda: False)
    link = FollowedEquity(
        symbol="LINK_ALPHA",
        token_address="0x" + "e" * 40,
        decimals=18,
        signal_strength=0.81,
        current_price_usd=9.0,
    )
    trader = SignalEquityTrader(
        config=SignalEquityTraderConfig(enabled=True),
        gas_protector=None,
        usdc_address="0x" + "f" * 40,
    )
    decision = _try_build_high_risk_loss_cut_decision(
        assets=[link],
        balances=Balances(usdt=0, usdc=15, wmatic=1, pol=1, total_portfolio_usd=140),
        risk_level="HIGH",
        state={},
        trader=trader,
        secs_cooldown=60,
        get_token_balance=lambda _a, _d: 12.0,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert decision is None
