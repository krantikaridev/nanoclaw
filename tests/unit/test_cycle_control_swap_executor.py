"""Integration tests for ``control.json`` overrides in ``determine_trade_decision``."""

import types

from external_layer.control import CycleControlSnapshot
from modules import swap_executor
from modules.runtime import Balances, TradeDecision


def test_paused_control_still_allows_protection_exit(monkeypatch):
    cs = types.SimpleNamespace()
    cs._log_trade_skipped = lambda *_a, **_k: None
    cs.get_target_wallets = lambda: []
    cs.can_trade_wallet = lambda *_a, **_k: True
    cs.can_trade_asset = lambda *_a, **_k: True
    cs.COOLDOWN_MINUTES = 1
    cs.PER_ASSET_COOLDOWN_MINUTES = 1
    cs.TAKE_PROFIT_PCT = 5.0
    cs.STRONG_SIGNAL_TP = 9.0
    cs.COPY_TRADE_PCT = 0.28
    cs.ENABLE_X_SIGNAL_EQUITY = False
    cs.ENABLE_USDC_COPY = False
    monkeypatch.setattr(swap_executor, "_facade", lambda: cs)
    monkeypatch.setattr(swap_executor, "cs_check_exit_conditions", lambda: (True, "prot"))
    monkeypatch.setattr(
        swap_executor,
        "cs_build_protection_exit_decision",
        lambda **_k: TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=10**17,
            trade_size=5.0,
            message="protection",
        ),
    )
    monkeypatch.setattr(swap_executor, "cs_evaluate_take_profit", lambda *_a, **_k: (False, None))
    monkeypatch.setattr(swap_executor, "cs_get_latest_open_trade", lambda *_a, **_k: None)
    monkeypatch.setattr(swap_executor, "is_copy_trading_enabled", lambda: False)

    state: dict = {}
    balances = Balances(usdt=50.0, usdc=50.0, wmatic=1.0, pol=1.0)
    ctrl = CycleControlSnapshot(paused=True)
    out = swap_executor.determine_trade_decision(state, balances, 1.0, cycle_control=ctrl)
    assert out.direction == "WMATIC_TO_USDT"


def test_paused_control_skips_main_strategy_buy(monkeypatch):
    cs = types.SimpleNamespace()
    cs._log_trade_skipped = lambda *_a, **_k: None
    cs.get_target_wallets = lambda: []
    cs.can_trade_wallet = lambda *_a, **_k: True
    cs.can_trade_asset = lambda *_a, **_k: True
    cs.COOLDOWN_MINUTES = 1
    cs.PER_ASSET_COOLDOWN_MINUTES = 1
    cs.TAKE_PROFIT_PCT = 5.0
    cs.STRONG_SIGNAL_TP = 9.0
    cs.COPY_TRADE_PCT = 0.28
    cs.ENABLE_X_SIGNAL_EQUITY = False
    cs.ENABLE_USDC_COPY = False
    cs.fixed_copy_trade_usd = lambda *_a, **_k: 15.0
    monkeypatch.setattr(swap_executor, "_facade", lambda: cs)
    monkeypatch.setattr(swap_executor, "cs_check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(swap_executor, "cs_evaluate_take_profit", lambda *_a, **_k: (False, None))
    monkeypatch.setattr(swap_executor, "is_copy_trading_enabled", lambda: False)

    state = {}
    balances = Balances(usdt=50.0, usdc=50.0, wmatic=0.1, pol=1.0)
    ctrl = CycleControlSnapshot(paused=True)
    out = swap_executor.determine_trade_decision(state, balances, 1.0, cycle_control=ctrl)
    assert "Paused via control.json" in (out.message or "")
    assert out.direction is None


def test_max_copy_trade_pct_overrides_polycopy_pct(monkeypatch):
    captured: dict[str, float] = {}

    def _capture_fixed(usdc, usdt, pct):
        captured["pct"] = float(pct)
        return 12.0

    cs = types.SimpleNamespace()
    cs._log_trade_skipped = lambda *_a, **_k: None
    cs.get_target_wallets = lambda: ["0x" + "a" * 40]
    cs.can_trade_wallet = lambda *_a, **_k: True
    cs.can_trade_asset = lambda *_a, **_k: True
    cs.COOLDOWN_MINUTES = 1
    cs.PER_ASSET_COOLDOWN_MINUTES = 1
    cs.TAKE_PROFIT_PCT = 5.0
    cs.STRONG_SIGNAL_TP = 9.0
    cs.COPY_TRADE_PCT = 0.28
    cs.PER_WALLET_COOLDOWN = 300
    cs.ENABLE_X_SIGNAL_EQUITY = False
    cs.ENABLE_USDC_COPY = False
    cs.fixed_copy_trade_usd = _capture_fixed
    monkeypatch.setattr(swap_executor, "_facade", lambda: cs)
    monkeypatch.setattr(swap_executor, "cs_check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(swap_executor, "cs_evaluate_take_profit", lambda *_a, **_k: (False, None))
    monkeypatch.setattr(swap_executor, "is_copy_trading_enabled", lambda: True)

    state = {}
    balances = Balances(usdt=50.0, usdc=50.0, wmatic=0.1, pol=1.0)
    ctrl = CycleControlSnapshot(max_copy_trade_pct=0.08)
    swap_executor.determine_trade_decision(state, balances, 1.0, cycle_control=ctrl)
    assert captured.get("pct") == 0.08


def test_main_strategy_ignores_max_copy_trade_pct(monkeypatch):
    captured: list[float] = []

    def _capture_fixed(usdc, usdt, pct):
        captured.append(float(pct))
        return 15.0

    cs = types.SimpleNamespace()
    cs._log_trade_skipped = lambda *_a, **_k: None
    cs.get_target_wallets = lambda: []
    cs.can_trade_wallet = lambda *_a, **_k: True
    cs.can_trade_asset = lambda *_a, **_k: True
    cs.COOLDOWN_MINUTES = 1
    cs.PER_ASSET_COOLDOWN_MINUTES = 1
    cs.TAKE_PROFIT_PCT = 5.0
    cs.STRONG_SIGNAL_TP = 9.0
    cs.COPY_TRADE_PCT = 0.28
    cs.ENABLE_X_SIGNAL_EQUITY = False
    cs.ENABLE_USDC_COPY = False
    cs.fixed_copy_trade_usd = _capture_fixed
    monkeypatch.setattr(swap_executor, "_facade", lambda: cs)
    monkeypatch.setattr(swap_executor, "cs_check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(swap_executor, "cs_evaluate_take_profit", lambda *_a, **_k: (False, None))
    monkeypatch.setattr(swap_executor, "is_copy_trading_enabled", lambda: False)

    state = {}
    balances = Balances(usdt=50.0, usdc=50.0, wmatic=0.1, pol=1.0)
    ctrl = CycleControlSnapshot(max_copy_trade_pct=0.08)
    swap_executor.determine_trade_decision(state, balances, 1.0, cycle_control=ctrl)
    assert captured == [0.28]
