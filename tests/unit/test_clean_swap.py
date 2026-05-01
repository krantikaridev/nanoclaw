import asyncio

import clean_swap


class _DummyGasProtector:
    def get_safe_status(self, address, urgent=False, min_pol=None):
        return {
            "gas_ok": True,
            "pol_balance": 1.0,
            "gas_gwei": 20.0,
            "max_gwei": 80.0,
        }


class _DummyTraderConfig:
    min_trade_usdc = 6.0
    per_asset_cooldown_seconds = 1800
    min_pol_for_gas = 0.005


class _DummyTunedTrader:
    def __init__(self):
        self.config = _DummyTraderConfig()
        self.gas_protector = _DummyGasProtector()
        self.build_plan_calls = 0

    def build_plan(self, **kwargs):
        self.build_plan_calls += 1
        return object()


def test_evaluate_usdc_copy_trade_defaults_strategy_without_build_call(monkeypatch):
    monkeypatch.setattr(clean_swap, "ENABLE_USDC_COPY", True)

    async def _once():
        return await clean_swap.evaluate_usdc_copy_trade(
            clean_swap.Balances(usdt=0.0, wmatic=0.0, pol=1.0, usdc=0.0),
            wallets=[],
            strategy=None,
        )

    out = asyncio.run(_once())
    assert "ℹ️" in (out.message or "")


def test_evaluate_usdc_copy_trade_returns_disabled_message_when_flag_off(monkeypatch):
    monkeypatch.setattr(clean_swap, "ENABLE_USDC_COPY", False)

    out = asyncio.run(
        clean_swap.evaluate_usdc_copy_trade(
            clean_swap.Balances(usdt=0.0, wmatic=0.0, pol=1.0, usdc=0.0),
            wallets=[],
        )
    )

    assert out.message == "ℹ️ USDC copy disabled"


def test_effective_take_profit_thresholds_bumps_strong_threshold_when_misconfigured(monkeypatch):
    monkeypatch.setattr(clean_swap, "TAKE_PROFIT_PCT", 10.0)
    monkeypatch.setattr(clean_swap, "STRONG_SIGNAL_TP", 9.0)

    base_tp, strong_tp = clean_swap._effective_take_profit_thresholds()

    assert base_tp == 10.0
    assert strong_tp == 14.0


def test_evaluate_take_profit_hits_strong_take_profit(monkeypatch):
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: {"buy_price": 1.0})
    state = {}

    should_exit, signal = clean_swap.evaluate_take_profit(1.13, state)

    assert should_exit is True
    assert signal["reason"] == "STRONG_TP_HIT"
    assert signal["sell_fraction"] == clean_swap.STRONG_TP_SELL_PCT
    assert state["profit_tracking"]["peak_price"] == 1.13


def test_evaluate_take_profit_hits_standard_take_profit(monkeypatch):
    monkeypatch.setattr(clean_swap, "TAKE_PROFIT_PCT", 8.0)
    monkeypatch.setattr(clean_swap, "STRONG_SIGNAL_TP", 12.0)
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: {"buy_price": 1.0})
    state = {}

    should_exit, signal = clean_swap.evaluate_take_profit(1.09, state)

    assert should_exit is True
    assert signal["reason"] == "TP_HIT"
    assert signal["sell_fraction"] == clean_swap.TAKE_PROFIT_SELL_PCT


def test_evaluate_take_profit_preserves_two_tiers_when_thresholds_overlap(monkeypatch):
    monkeypatch.setattr(clean_swap, "TAKE_PROFIT_PCT", 12.0)
    monkeypatch.setattr(clean_swap, "STRONG_SIGNAL_TP", 12.0)
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: {"buy_price": 1.0})
    state = {}

    should_exit, signal = clean_swap.evaluate_take_profit(1.12, state)

    assert should_exit is True
    assert signal["reason"] == "TP_HIT"
    assert signal["sell_fraction"] == clean_swap.TAKE_PROFIT_SELL_PCT


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


def test_evaluate_take_profit_returns_none_and_clears_tracking_for_invalid_buy_price(monkeypatch):
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: {"buy_price": 0.0})
    state = {"profit_tracking": {"buy_price": 1.0, "peak_price": 1.2}}

    should_exit, signal = clean_swap.evaluate_take_profit(1.05, state)

    assert should_exit is False
    assert signal is None
    assert state["profit_tracking"] == {}


def test_evaluate_take_profit_returns_hold_signal_when_no_exit_conditions_hit(monkeypatch):
    monkeypatch.setattr(clean_swap, "get_latest_open_trade", lambda trade_log_file=clean_swap.TRADE_LOG_FILE: {"buy_price": 1.0})
    state = {}

    should_exit, signal = clean_swap.evaluate_take_profit(1.02, state)

    assert should_exit is False
    assert signal["reason"] == "HOLD"
    assert signal["sell_fraction"] == 0.0


def test_build_protection_exit_decision_uses_strong_tp_sell_fraction(monkeypatch):
    monkeypatch.setattr(clean_swap, "_effective_take_profit_thresholds", lambda: (8.0, 12.0))
    decision = clean_swap.build_protection_exit_decision(
        reason="PER_TRADE_EXIT",
        current_price=1.20,
        wmatic_balance=10.0,
        open_trade={"buy_price": 1.0},
    )

    assert decision.direction == "WMATIC_TO_USDT"
    assert decision.amount_in == int(10.0 * clean_swap.STRONG_TP_SELL_PCT * 1e18)
    assert "strong TP hit" in decision.message


def test_build_protection_exit_decision_uses_default_message_for_non_trade_reason():
    decision = clean_swap.build_protection_exit_decision(
        reason="GUARD_TRIGGERED",
        current_price=1.0,
        wmatic_balance=10.0,
        open_trade=None,
    )

    assert decision.direction == "WMATIC_TO_USDT"
    assert decision.amount_in == int(10.0 * 0.45 * 1e18)
    assert "PROTECTION TRIGGERED" in decision.message


def test_build_profit_exit_decision_clamps_sell_fraction_bounds():
    low = clean_swap.build_profit_exit_decision(
        {"reason": "TP_HIT", "message": "low", "sell_fraction": 0.01},
        wmatic_balance=10.0,
    )
    high = clean_swap.build_profit_exit_decision(
        {"reason": "TP_HIT", "message": "high", "sell_fraction": 5.0},
        wmatic_balance=10.0,
    )

    assert low.amount_in == int(10.0 * 0.1 * 1e18)
    assert high.amount_in == int(10.0 * 1.0 * 1e18)


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


def test_select_main_strategy_takes_profit_when_wmatic_value_is_high():
    decision = clean_swap.select_main_strategy_trade(
        clean_swap.Balances(usdt=30.0, wmatic=60.0, pol=1.0),
        current_price=1.0,
    )

    assert decision.direction == "WMATIC_TO_USDT"
    assert "Taking profit" in decision.message


def test_select_main_strategy_cuts_loss_when_wmatic_value_is_low_and_size_is_large():
    decision = clean_swap.select_main_strategy_trade(
        clean_swap.Balances(usdt=30.0, wmatic=60.0, pol=1.0),
        current_price=0.6,
    )

    assert decision.direction == "WMATIC_TO_USDT"
    assert decision.amount_in == int(60.0 * 0.28 * 1e18)
    assert "Cutting loss" in decision.message


def test_select_copy_trade_skips_when_all_wallets_are_on_cooldown(monkeypatch):
    logs = []
    monkeypatch.setattr(clean_swap, "can_trade_wallet", lambda wallet: False)
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: logs.append(reason))

    decision = clean_swap.select_copy_trade(
        clean_swap.Balances(usdt=100.0, wmatic=10.0, pol=1.0, usdc=0.0),
        wallets=["0x1", "0x2"],
    )

    assert decision.direction is None
    assert "TRADE SKIPPED: cooldown" in decision.message
    assert logs


def test_select_copy_trade_executes_when_at_least_one_wallet_is_eligible(monkeypatch):
    monkeypatch.setattr(clean_swap, "can_trade_wallet", lambda wallet: wallet == "0x2")

    decision = clean_swap.select_copy_trade(
        clean_swap.Balances(usdt=100.0, wmatic=10.0, pol=1.0, usdc=0.0),
        wallets=["0x1", "0x2"],
    )

    assert decision.direction == "USDT_TO_WMATIC"
    assert decision.trade_size == 18.0
    assert decision.amount_in == int(18.0 * 1_000_000)


def test_global_cooldown_uses_last_run_timestamp():
    assert clean_swap.is_global_cooldown_active({"last_run": 950}, cooldown_minutes=1, now=1000) is True
    assert clean_swap.is_global_cooldown_active({"last_run": 930}, cooldown_minutes=1, now=1000) is False


def test_wallet_cooldown_blocks_until_threshold_passes():
    clean_swap.WALLET_LAST_TRADE.clear()
    wallet = "0xabc"

    clean_swap.mark_wallet_traded(wallet, now=1000, cooldown_seconds=300)

    assert clean_swap.can_trade_wallet(wallet, now=1200, cooldown_seconds=300) is False
    assert clean_swap.can_trade_wallet(wallet, now=1301, cooldown_seconds=300) is True


def test_portfolio_history_uses_independent_pol_price(monkeypatch, tmp_path):
    csv_path = tmp_path / "portfolio_history.csv"
    monkeypatch.setattr(clean_swap, "PORTFOLIO_HISTORY_FILE", str(csv_path))
    monkeypatch.setattr(clean_swap, "POL_USD_PRICE", 0.25)
    monkeypatch.setattr(clean_swap, "USDT", "0xusdt")
    monkeypatch.setattr(clean_swap, "USDC", "0xusdc")
    monkeypatch.setattr(clean_swap, "WMATIC", "0xwmatic")

    def _token_balance(token_address, decimals=6, web3_client=None, wallet_address=None):
        if token_address == "0xusdt":
            return 50.0
        if token_address == "0xusdc":
            return 10.0
        if token_address == "0xwmatic":
            return 5.0
        return 0.0

    monkeypatch.setattr(clean_swap, "get_token_balance", _token_balance)
    monkeypatch.setattr(clean_swap, "get_pol_balance", lambda wallet_address=clean_swap.WALLET: 20.0)

    clean_swap.write_portfolio_history_snapshot(current_price=2.0)

    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value"
    # total_value = 50 + 10 + (5 * 2.0) + (20 * 0.25) = 75.0
    assert lines[1].endswith(",20.000000,0.250000,75.000000")


def test_x_signal_buy_paths_block_when_topup_reports_success_but_pol_remains_low(monkeypatch):
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "AUTO_TOPUP_POL", True)
    monkeypatch.setattr(clean_swap, "MIN_POL_FOR_GAS", 0.005)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)

    base_trader = type(
        "BaseTrader",
        (),
        {
            "load_followed_equities": lambda self: [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                )
            ]
        },
    )()
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", base_trader)

    tuned_trader = _DummyTunedTrader()
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: tuned_trader)
    monkeypatch.setattr(clean_swap, "ensure_pol_for_trade", lambda min_pol=0.005: True)

    balances_sequence = [
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=0.001, usdc=20.0),
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=0.001, usdc=20.0),
    ]

    def _get_balances():
        return balances_sequence.pop(0) if balances_sequence else clean_swap.Balances(
            usdt=40.0, wmatic=10.0, pol=0.001, usdc=20.0
        )

    monkeypatch.setattr(clean_swap, "get_balances", _get_balances)
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=0.001, usdc=20.0),
        dry_run=False,
    )

    assert decision is None
    assert tuned_trader.build_plan_calls == 0


def test_determine_trade_decision_prioritizes_protection_first(monkeypatch):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (True, "PER_TRADE_EXIT"))
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: [])

    sentinel = clean_swap.TradeDecision(direction="WMATIC_TO_USDT", amount_in=123, message="protection")
    monkeypatch.setattr(clean_swap, "build_protection_exit_decision", lambda **kwargs: sentinel)
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=10.0, wmatic=5.0, pol=1.0, usdc=2.0),
        current_price=1.0,
    )

    assert out is sentinel


def test_determine_trade_decision_prioritizes_profit_take_over_xsignal(monkeypatch):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(
        clean_swap,
        "evaluate_take_profit",
        lambda *_args, **_kwargs: (True, {"reason": "TP_HIT", "message": "tp", "sell_fraction": 0.45}),
    )
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: [])
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)

    sentinel = clean_swap.TradeDecision(direction="WMATIC_TO_USDT", amount_in=456, message="profit")
    monkeypatch.setattr(clean_swap, "build_profit_exit_decision", lambda *_args, **_kwargs: sentinel)

    # Should never be reached because profit-take returns first.
    monkeypatch.setattr(
        clean_swap,
        "try_x_signal_equity_decision",
        lambda *_args, **_kwargs: clean_swap.TradeDecision(direction="USDC_TO_WMATIC", amount_in=999, message="x"),
    )

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=10.0, wmatic=5.0, pol=1.0, usdc=2.0),
        current_price=1.0,
    )

    assert out is sentinel


def test_determine_trade_decision_uses_xsignal_before_copy_and_main(monkeypatch):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: ["0xwallet"])

    sentinel = clean_swap.TradeDecision(direction="USDC_TO_EQUITY", amount_in=789, message="x-signal")
    monkeypatch.setattr(clean_swap, "try_x_signal_equity_decision", lambda *_args, **_kwargs: sentinel)

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=10.0, wmatic=5.0, pol=1.0, usdc=10.0),
        current_price=1.0,
    )

    assert out is sentinel


def test_main_skips_cycle_on_global_cooldown_and_logs_reason(monkeypatch):
    monkeypatch.setattr(clean_swap, "load_state", lambda: {"last_run": 1000.0})
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=10.0, wmatic=5.0, pol=1.0, usdc=2.0),
    )
    monkeypatch.setattr(clean_swap, "has_active_lock", lambda: False)
    monkeypatch.setattr(clean_swap, "create_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "release_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 1.0)
    monkeypatch.setattr(clean_swap, "write_portfolio_history_snapshot", lambda _price: None)
    monkeypatch.setattr(clean_swap, "is_global_cooldown_active", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(clean_swap.time, "time", lambda: 1060.0)

    logs = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: logs.append(reason))

    asyncio.run(clean_swap.main(dry_run=True))

    assert logs
    assert "cooldown (global" in logs[0]
