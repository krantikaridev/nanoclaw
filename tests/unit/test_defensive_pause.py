import types

import config as cfg

from modules.runtime import Balances, TradeDecision
from modules import swap_executor


class _FakeCopyPlan:
    def __init__(self) -> None:
        self.amount_in = 12_000_000
        self.trade_size = 12.0
        self.message = "copy plan"
        self.wallet = "0x" + "1" * 40


class _FakeCopyStrategy:
    class _C:
        per_wallet_cooldown_seconds = 300

    config = _C()

    def build_plan(self, **_kwargs):
        return _FakeCopyPlan()


def test_defensive_pause_blocks_x_signal_buy_and_copy_trades(monkeypatch):
    # Make HIGH-risk easy to hit: HIGH when usdt < (threshold + 3).
    monkeypatch.setattr(cfg, "PROTECTION_FLUCTUATION_USDT_THRESHOLD", 10.0, raising=False)
    monkeypatch.setattr(cfg, "PROTECTION_FLUCTUATION_MIN_WMATIC", 0.0, raising=False)

    # Stub clean_swap facade used by swap_executor.determine_trade_decision.
    cs = types.SimpleNamespace()
    cs.ENABLE_X_SIGNAL_EQUITY = True
    cs.ENABLE_USDC_COPY = True
    cs.PER_WALLET_COOLDOWN = 300
    cs.COPY_TRADE_PCT = 0.2
    cs._log_trade_skipped = lambda *_a, **_k: None
    cs.get_target_wallets = lambda: ["0x" + "2" * 40]
    cs.can_trade_wallet = lambda *_a, **_k: True
    cs.can_trade_asset = lambda *_a, **_k: True
    cs.COOLDOWN_MINUTES = 1
    cs.PER_ASSET_COOLDOWN_MINUTES = 1
    cs.TAKE_PROFIT_PCT = 5.0
    cs.STRONG_SIGNAL_TP = 9.0
    cs.WALLET = "0x" + "3" * 40
    cs.fixed_copy_trade_usd = lambda *_a, **_k: 12.0

    # Exit checks should not interfere.
    monkeypatch.setattr(swap_executor, "cs_check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(swap_executor, "cs_evaluate_take_profit", lambda *_a, **_k: (False, None))

    # Always propose an X-signal BUY entry.
    monkeypatch.setattr(
        swap_executor,
        "cs_try_x_signal_equity_decision",
        lambda *_a, **_k: TradeDecision(direction="USDC_TO_EQUITY", amount_in=10_000_000, message="x buy"),
    )
    monkeypatch.setattr(swap_executor, "_facade", lambda: cs)
    monkeypatch.setattr(swap_executor, "is_copy_trading_enabled", lambda: True)
    monkeypatch.setattr(swap_executor, "USDC_COPY_STRATEGY", _FakeCopyStrategy())

    state = {}
    # Cycle 1: HIGH risk, streak=1 -> no defensive pause yet; should take X-signal BUY.
    b1 = Balances(usdt=11.0, usdc=50.0, wmatic=0.0, pol=1.0)
    d1 = swap_executor.determine_trade_decision(state, b1, current_price=1.0, dry_run=True)
    assert d1.direction == "USDC_TO_EQUITY"

    # Cycle 2: HIGH risk again, streak=2 -> defensive pause activates; blocks X-signal BUY and copy trades.
    b2 = Balances(usdt=11.0, usdc=50.0, wmatic=0.0, pol=1.0)
    d2 = swap_executor.determine_trade_decision(state, b2, current_price=1.0, dry_run=True)
    # Falls through to non-entry paths (main strategy / protection), not X-signal BUY or copy-trade entry.
    assert d2.direction != "USDC_TO_EQUITY"
    assert d2.direction != "USDC_TO_WMATIC"

    # Cycle 3: risk drops to LOW -> defensive pause clears; X-signal BUY resumes.
    b3 = Balances(usdt=25.0, usdc=50.0, wmatic=0.0, pol=1.0)
    d3 = swap_executor.determine_trade_decision(state, b3, current_price=1.0, dry_run=True)
    assert d3.direction == "USDC_TO_EQUITY"

