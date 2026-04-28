import clean_swap


def test_evaluate_take_profit_hits_strong_take_profit(monkeypatch):
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: {"buy_price": 1.0})
    state = {}

    should_exit, signal = clean_swap.evaluate_take_profit(1.13, state)

    assert should_exit is True
    assert signal["reason"] == "STRONG_TP_HIT"
    assert signal["sell_fraction"] == clean_swap.STRONG_TP_SELL_PCT
    assert state["profit_tracking"]["peak_price"] == 1.13


def test_evaluate_take_profit_hits_trailing_stop_after_pullback(monkeypatch):
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: {"buy_price": 1.0})
    state = {"profit_tracking": {"buy_price": 1.0, "peak_price": 1.10}}

    should_exit, signal = clean_swap.evaluate_take_profit(1.04, state)

    assert should_exit is True
    assert signal["reason"] == "TRAILING_STOP_HIT"
    assert signal["pullback_pct"] >= clean_swap.TRAILING_STOP_PCT


def test_evaluate_take_profit_resets_tracking_without_open_trade(monkeypatch):
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: None)
    state = {"profit_tracking": {"buy_price": 1.0, "peak_price": 1.2}}

    should_exit, signal = clean_swap.evaluate_take_profit(1.05, state)

    assert should_exit is False
    assert signal is None
    assert state["profit_tracking"] == {}


def test_select_main_strategy_prefers_usdt_reserve_protection():
    decision = clean_swap.select_main_strategy_trade(
        clean_swap.Balances(usdt=20.0, wmatic=80.0, pol=1.0),
        current_price=0.95,
    )

    assert decision.direction == "WMATIC_TO_USDT"
    assert "USDT RESERVE PROTECTION" in decision.message


def test_select_main_strategy_buys_when_balances_are_healthy():
    decision = clean_swap.select_main_strategy_trade(
        clean_swap.Balances(usdt=80.0, wmatic=20.0, pol=1.0),
        current_price=0.75,
    )

    assert decision.direction == "USDT_TO_WMATIC"
    assert decision.trade_size > 0
    assert decision.amount_in == int(decision.trade_size * 1_000_000)


def test_global_cooldown_uses_last_run_timestamp():
    assert clean_swap.is_global_cooldown_active({"last_run": 950}, cooldown_minutes=1, now=1000) is True
    assert clean_swap.is_global_cooldown_active({"last_run": 930}, cooldown_minutes=1, now=1000) is False


def test_wallet_cooldown_blocks_until_threshold_passes():
    clean_swap.WALLET_LAST_TRADE.clear()
    wallet = "0xabc"

    clean_swap.mark_wallet_traded(wallet, now=1000, cooldown_seconds=300)

    assert clean_swap.can_trade_wallet(wallet, now=1200, cooldown_seconds=300) is False
    assert clean_swap.can_trade_wallet(wallet, now=1301, cooldown_seconds=300) is True
