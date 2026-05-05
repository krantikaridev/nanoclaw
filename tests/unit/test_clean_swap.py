import asyncio
from datetime import datetime
import json

import clean_swap
from modules import swap_executor as swap_exec


def test_log_format_prefixes_short_commit_hash():
    assert clean_swap.COMMIT
    assert f"[{clean_swap.COMMIT}]" in clean_swap.LOG_FORMAT


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

    def build_plan_with_block_reason(self, **kwargs):
        self.build_plan_calls += 1
        return object(), None

    def build_plan(self, **kwargs):
        plan, _ = self.build_plan_with_block_reason(**kwargs)
        return plan


def test_parse_balance_config_reads_expected_values(tmp_path):
    config_path = tmp_path / "balance_config.txt"
    config_path.write_text(
        "\n".join(
            [
                "USDC=66.85",
                "WMATIC=4.60",
                "USDT=31.13",
                "IGNORED=1.0",
            ]
        ),
        encoding="utf-8",
    )

    usdc, wmatic, usdt = clean_swap._parse_balance_config(config_path)

    assert usdc == 66.85
    assert wmatic == 4.60
    assert usdt == 31.13


def test_parse_balance_config_returns_none_when_file_missing_or_empty(tmp_path):
    missing = tmp_path / "missing_balance_config.txt"
    assert clean_swap._parse_balance_config(missing) is None

    empty = tmp_path / "empty_balance_config.txt"
    empty.write_text("", encoding="utf-8")
    assert clean_swap._parse_balance_config(empty) is None


def test_append_balance_log_line_writes_total_and_source(tmp_path):
    log_file = tmp_path / "real_cron.log"

    line = clean_swap._append_balance_log_line(
        66.85,
        4.60,
        31.13,
        source="BotLogger",
        log_file=log_file,
        now=datetime(2026, 5, 4, 10, 22, 33),
    )

    assert "MANUAL CORRECT BALANCE" in line
    assert "USDC=$66.85" in line
    assert "WMATIC=$4.60" in line
    assert "USDT=$31.13" in line
    assert "TOTAL=$102.58" in line
    assert "Source=BotLogger" in line
    assert log_file.read_text(encoding="utf-8").strip() == line


def test_log_balance_from_config_skips_missing_or_empty_without_writing(tmp_path):
    missing = tmp_path / "missing_balance_config.txt"
    log_file = tmp_path / "real_cron.log"
    clean_swap._log_balance_from_config(config_path=missing, log_file=log_file, source="BotLogger")
    assert not log_file.exists()

    empty = tmp_path / "empty_balance_config.txt"
    empty.write_text("", encoding="utf-8")
    clean_swap._log_balance_from_config(config_path=empty, log_file=log_file, source="BotLogger")
    assert not log_file.exists()


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


def test_build_protection_exit_decision_includes_fluctuation_context(monkeypatch):
    import protection

    monkeypatch.setattr(
        protection,
        "get_last_fluctuation_context",
        lambda: {
            "usdt": 22.5,
            "wmatic": 55.0,
            "usdt_threshold": 30.0,
            "wmatic_min": 50.0,
            "sell_fraction": 0.25,
            "sell_amount_wmatic": 20.0,
            "sell_notional_usd": 16.2,
            "min_sell_usd": 8.0,
        },
    )
    decision = clean_swap.build_protection_exit_decision(
        reason="FLUCTUATION",
        current_price=1.0,
        wmatic_balance=80.0,
        open_trade=None,
    )

    assert "PROTECTION TRIGGERED: FLUCTUATION" in decision.message
    assert "USDT=$22.50" in decision.message
    assert "WMATIC=55.0000" in decision.message
    assert "sell=25%" in decision.message
    assert "notional=$16.20 (min=$8.00)" in decision.message
    assert decision.amount_in == int(80.0 * 0.25 * 1e18)


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
    monkeypatch.setattr(clean_swap, "COPY_TRADE_PCT", 0.28)
    monkeypatch.setattr(clean_swap, "can_trade_wallet", lambda wallet: wallet == "0x2")

    decision = clean_swap.select_copy_trade(
        clean_swap.Balances(usdt=100.0, wmatic=10.0, pol=1.0, usdc=0.0),
        wallets=["0x1", "0x2"],
    )

    assert decision.direction == "USDT_TO_WMATIC"
    assert decision.trade_size == 10.0  # 100*0.28→$28 capped to FIXED_TRADE_USD_MAX (default 10)
    assert decision.amount_in == int(10.0 * 1_000_000)


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
    class _LowPolGasProtector:
        def get_safe_status(self, address, urgent=False, min_pol=None):
            return {
                "gas_ok": True,
                "pol_balance": 0.001,  # Low POL to trigger block
                "gas_gwei": 20.0,
                "max_gwei": 80.0,
            }

    class _LowPolTunedTrader:
        def __init__(self):
            self.config = _DummyTraderConfig()
            self.gas_protector = _LowPolGasProtector()
            self.build_plan_calls = 0

        def build_plan_with_block_reason(self, **kwargs):
            self.build_plan_calls += 1
            # Simulate POL check failure
            return None, "pol_below_min"

        def build_plan(self, **kwargs):
            plan, _ = self.build_plan_with_block_reason(**kwargs)
            return plan

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

    tuned_trader = _LowPolTunedTrader()
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
    assert tuned_trader.build_plan_calls == 1  # Called but POL check fails inside


def test_determine_trade_decision_prioritizes_protection_first(monkeypatch):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (True, "PER_TRADE_EXIT"))
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: [])
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 0.0)

    sentinel = clean_swap.TradeDecision(direction="WMATIC_TO_USDT", amount_in=123, message="protection")
    monkeypatch.setattr(clean_swap, "build_protection_exit_decision", lambda **kwargs: sentinel)
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=10.0, wmatic=5.0, pol=1.0, usdc=2.0),
        current_price=1.0,
    )

    assert out is sentinel


def test_determine_trade_decision_defers_dust_protection_and_falls_through(monkeypatch, capsys):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (True, "PER_TRADE_EXIT"))
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 15.0)
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: [])

    protection_dust = clean_swap.TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),  # $5.00 at current_price=1.0
        message="protection dust",
    )
    monkeypatch.setattr(clean_swap, "build_protection_exit_decision", lambda **kwargs: protection_dust)
    sentinel = clean_swap.TradeDecision(direction="USDC_TO_EQUITY", amount_in=25_000_000, message="x-signal")
    monkeypatch.setattr(clean_swap, "try_x_signal_equity_decision", lambda *_args, **_kwargs: sentinel)

    skipped: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: skipped.append(reason))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=10.0, wmatic=5.0, pol=1.0, usdc=30.0),
        current_price=1.0,
    )

    captured = capsys.readouterr().out
    assert out is sentinel
    assert any("protection_dust_deferred" in reason for reason in skipped)
    assert "PROTECTION DUST DEFER" in captured
    assert "continuing to next strategy" in captured


def test_determine_trade_decision_prioritizes_profit_take_over_xsignal(monkeypatch):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 0.0)
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
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 0.0)
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


def test_determine_trade_decision_defers_dust_profit_take_and_falls_through(monkeypatch, capsys):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(
        clean_swap,
        "evaluate_take_profit",
        lambda *_args, **_kwargs: (True, {"reason": "TP_HIT", "message": "tp", "sell_fraction": 0.12}),
    )
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 15.0)
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: [])

    profit_dust = clean_swap.TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(5 * 1_000_000_000_000_000_000),
        message="tiny tp",
    )
    sentinel = clean_swap.TradeDecision(direction="USDC_TO_EQUITY", amount_in=25_000_000, message="x-signal")
    monkeypatch.setattr(clean_swap, "build_profit_exit_decision", lambda *_args, **_kwargs: profit_dust)
    monkeypatch.setattr(clean_swap, "try_x_signal_equity_decision", lambda *_args, **_kwargs: sentinel)

    skipped: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: skipped.append(reason))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=10.0, wmatic=5.0, pol=1.0, usdc=30.0),
        current_price=1.0,
    )

    captured = capsys.readouterr().out
    assert out is sentinel
    assert any("profit_take_dust_deferred" in reason for reason in skipped)
    assert "PROFIT_TAKE DUST DEFER" in captured
    assert "continuing to next strategy" in captured


def test_determine_trade_decision_defers_dust_x_signal_and_falls_through_to_main(monkeypatch, capsys):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 15.0)
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: [])

    x_dust = clean_swap.TradeDecision(
        direction="USDC_TO_EQUITY",
        amount_in=int(4.15 * 1_000_000),
        trade_size=4.15,
        message="tiny x buy",
        token_in="0x" + "2" * 40,
        token_out="0x" + "1" * 40,
    )
    main_ok = clean_swap.TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(20 * 1_000_000),
        trade_size=20.0,
        message="main buy",
    )
    monkeypatch.setattr(clean_swap, "try_x_signal_equity_decision", lambda *_args, **_kwargs: x_dust)
    monkeypatch.setattr(swap_exec, "select_main_strategy_trade", lambda *_args, **_kwargs: main_ok)

    skipped: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: skipped.append(reason))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=40.0, wmatic=5.0, pol=1.0, usdc=10.0),
        current_price=1.0,
    )

    captured = capsys.readouterr().out
    assert out is main_ok
    assert any("x_signal_equity_dust_deferred" in reason for reason in skipped)
    assert "X_SIGNAL_EQUITY DUST DEFER" in captured
    assert "DECISION PATH: MAIN_STRATEGY" in captured


def test_determine_trade_decision_defers_dust_usdc_copy_and_falls_through_to_main(monkeypatch, capsys):
    class _CopyPlan:
        amount_in = int(4.0 * 1_000_000)
        trade_size = 4.0
        message = "tiny usdc copy"
        wallet = "0xwallet"

    class _USDCopyStrategyStub:
        class config:
            per_wallet_cooldown_seconds = 300

        def build_plan(self, **kwargs):
            _ = kwargs
            return _CopyPlan()

    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 15.0)
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", False)
    monkeypatch.setattr(clean_swap, "ENABLE_USDC_COPY", True)
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: ["0xwallet"])
    monkeypatch.setattr(swap_exec, "is_copy_trading_enabled", lambda: True)
    monkeypatch.setattr(swap_exec, "USDC_COPY_STRATEGY", _USDCopyStrategyStub())

    main_ok = clean_swap.TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(18.0 * 1_000_000),
        trade_size=18.0,
        message="main buy",
    )
    monkeypatch.setattr(swap_exec, "select_main_strategy_trade", lambda *_args, **_kwargs: main_ok)

    skipped: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: skipped.append(reason))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=40.0, wmatic=5.0, pol=1.0, usdc=10.0),
        current_price=1.0,
    )

    captured = capsys.readouterr().out
    assert out is main_ok
    assert any("usdc_copy_dust_deferred" in reason for reason in skipped)
    assert "USDC_COPY DUST DEFER" in captured
    assert "No eligible copy-trade this cycle" not in captured
    assert "DECISION PATH: MAIN_STRATEGY" in captured


def test_determine_trade_decision_defers_dust_polycopy_and_falls_through_to_main(monkeypatch, capsys):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 15.0)
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", False)
    monkeypatch.setattr(clean_swap, "ENABLE_USDC_COPY", False)
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: ["0xwallet"])
    monkeypatch.setattr(swap_exec, "is_copy_trading_enabled", lambda: True)

    polycopy_dust = clean_swap.TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(4.0 * 1_000_000),
        trade_size=4.0,
        message="tiny copy",
    )
    main_ok = clean_swap.TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(18.0 * 1_000_000),
        trade_size=18.0,
        message="main buy",
    )
    monkeypatch.setattr(swap_exec, "select_copy_trade", lambda *_args, **_kwargs: polycopy_dust)
    monkeypatch.setattr(swap_exec, "select_main_strategy_trade", lambda *_args, **_kwargs: main_ok)

    skipped: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: skipped.append(reason))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=40.0, wmatic=5.0, pol=1.0, usdc=10.0),
        current_price=1.0,
    )

    captured = capsys.readouterr().out
    assert out is main_ok
    assert any("polycopy_dust_deferred" in reason for reason in skipped)
    assert "POLYCOPY DUST DEFER" in captured
    assert "DECISION PATH: MAIN_STRATEGY" in captured


def test_determine_trade_decision_defers_dust_main_strategy_with_no_further_fallback(monkeypatch, capsys):
    monkeypatch.setattr(clean_swap, "check_exit_conditions", lambda: (False, None))
    monkeypatch.setattr(clean_swap, "evaluate_take_profit", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 15.0)
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", False)
    monkeypatch.setattr(clean_swap, "get_target_wallets", lambda: [])

    main_dust = clean_swap.TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(4.0 * 1_000_000_000_000_000_000),
        message="tiny main sell",
    )
    monkeypatch.setattr(swap_exec, "select_main_strategy_trade", lambda *_args, **_kwargs: main_dust)

    skipped: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: skipped.append(reason))

    out = clean_swap.determine_trade_decision(
        state={},
        balances=clean_swap.Balances(usdt=40.0, wmatic=5.0, pol=1.0, usdc=0.0),
        current_price=1.0,
    )

    captured = capsys.readouterr().out
    assert out.should_execute is False
    assert "deferred" in out.message.lower()
    assert any("main_strategy_dust_deferred" in reason for reason in skipped)
    assert "MAIN_STRATEGY DUST DEFER" in captured


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


def test_main_skips_small_stable_in_trade_when_below_min_trade_usd(monkeypatch, capsys):
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "load_state", lambda: {"last_run": 0.0})
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=5.0, pol=1.0, usdc=10.0),
    )
    monkeypatch.setattr(clean_swap, "has_active_lock", lambda: False)
    monkeypatch.setattr(clean_swap, "create_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "release_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 1.0)
    monkeypatch.setattr(clean_swap, "write_portfolio_history_snapshot", lambda _price: None)
    monkeypatch.setattr(clean_swap, "is_global_cooldown_active", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(clean_swap, "save_state", lambda _state: None)
    monkeypatch.setattr(clean_swap, "get_pol_balance", lambda: 1.0)
    monkeypatch.setattr(
        clean_swap,
        "get_gas_status",
        lambda: {
            "ok": True,
            "gas_gwei": 20.0,
            "max_gwei": 80.0,
            "pol_balance": 1.0,
            "min_pol_balance": 0.005,
        },
    )
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 22.0)

    logs: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: logs.append(reason))

    async def _unexpected_swap(*_args, **_kwargs):
        raise AssertionError("approve_and_swap should not be called for sub-minimum trade")

    monkeypatch.setattr(
        swap_exec,
        "determine_trade_decision",
        lambda *_args, **_kwargs: clean_swap.TradeDecision(
            direction="USDC_TO_EQUITY",
            amount_in=int(4.5 * 1_000_000),
            trade_size=4.5,
            message="tiny x-signal buy",
            token_in="0x" + "2" * 40,
            token_out="0x" + "1" * 40,
        ),
    )
    monkeypatch.setattr(swap_exec, "approve_and_swap", _unexpected_swap)

    asyncio.run(clean_swap.main(dry_run=False))

    out = capsys.readouterr().out
    assert any("min_trade_guard" in x for x in logs)
    assert "TRADE SKIPPED | below minimum size" in out


def test_main_skips_small_wmatic_exit_when_below_min_trade_usd(monkeypatch, capsys):
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "load_state", lambda: {"last_run": 0.0})
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=20.0, pol=1.0, usdc=10.0),
    )
    monkeypatch.setattr(clean_swap, "has_active_lock", lambda: False)
    monkeypatch.setattr(clean_swap, "create_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "release_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    monkeypatch.setattr(clean_swap, "write_portfolio_history_snapshot", lambda _price: None)
    monkeypatch.setattr(clean_swap, "is_global_cooldown_active", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(clean_swap, "save_state", lambda _state: None)
    monkeypatch.setattr(clean_swap, "get_pol_balance", lambda: 1.0)
    monkeypatch.setattr(
        clean_swap,
        "get_gas_status",
        lambda: {
            "ok": True,
            "gas_gwei": 20.0,
            "max_gwei": 80.0,
            "pol_balance": 1.0,
            "min_pol_balance": 0.005,
        },
    )
    monkeypatch.setattr(clean_swap, "MIN_TRADE_USD", 22.0)

    logs: list[str] = []
    monkeypatch.setattr(clean_swap, "_log_trade_skipped", lambda reason: logs.append(reason))

    async def _unexpected_swap(*_args, **_kwargs):
        raise AssertionError("approve_and_swap should not be called for sub-minimum trade")

    monkeypatch.setattr(
        swap_exec,
        "determine_trade_decision",
        lambda *_args, **_kwargs: clean_swap.TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(8 * 1_000_000_000_000_000_000),
            message="tiny main strategy exit",
        ),
    )
    monkeypatch.setattr(swap_exec, "approve_and_swap", _unexpected_swap)

    asyncio.run(clean_swap.main(dry_run=False))

    out = capsys.readouterr().out
    assert any("min_trade_guard" in x for x in logs)
    assert "TRADE SKIPPED | below minimum size" in out


def test_main_records_wallet_performance_on_wmatic_to_usdc_exit(monkeypatch):
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "load_state", lambda: {"last_run": 0.0})
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=20.0, pol=1.0, usdc=10.0),
    )
    monkeypatch.setattr(clean_swap, "has_active_lock", lambda: False)
    monkeypatch.setattr(clean_swap, "create_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "release_lock", lambda: None)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    monkeypatch.setattr(clean_swap, "write_portfolio_history_snapshot", lambda _price: None)
    monkeypatch.setattr(clean_swap, "is_global_cooldown_active", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(clean_swap, "save_state", lambda _state: None)
    monkeypatch.setattr(clean_swap, "get_pol_balance", lambda: 1.0)
    monkeypatch.setattr(
        clean_swap,
        "get_gas_status",
        lambda: {
            "ok": True,
            "gas_gwei": 20.0,
            "max_gwei": 80.0,
            "pol_balance": 1.0,
            "min_pol_balance": 0.005,
        },
    )

    monkeypatch.setattr(
        swap_exec,
        "determine_trade_decision",
        lambda *_args, **_kwargs: clean_swap.TradeDecision(
            direction="WMATIC_TO_USDC",
            amount_in=int(4 * 1_000_000_000_000_000_000),
            message="wmatic to usdc exit",
        ),
    )
    async def _approve_and_swap(*_args, **_kwargs):
        return "0xhash"

    monkeypatch.setattr(swap_exec, "approve_and_swap", _approve_and_swap)
    monkeypatch.setattr(clean_swap, "mark_asset_traded", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clean_swap, "mark_wallet_traded", lambda *_args, **_kwargs: None)

    captured: dict[str, float] = {}

    def _record_copy_exit(*, exit_price_usd, exit_notional_usd):
        captured["exit_price_usd"] = float(exit_price_usd)
        captured["exit_notional_usd"] = float(exit_notional_usd)
        return []

    monkeypatch.setattr(swap_exec.wallet_performance, "record_copy_exit", _record_copy_exit)

    asyncio.run(clean_swap.main(dry_run=False))

    assert captured["exit_price_usd"] == 2.0
    assert captured["exit_notional_usd"] == 8.0


def test_try_x_signal_equity_decision_applies_dynamic_size_for_strong_buy(monkeypatch):
    class _Plan:
        direction = "USDC_TO_EQUITY"
        amount_in = 1
        trade_size = 20.0
        message = "buy"
        token_in = "0x" + "2" * 40
        token_out = "0x" + "1" * 40

    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan(self, **kwargs):
            _ = kwargs
            return _Plan()

        def build_plan_with_block_reason(self, **kwargs):
            return self.build_plan(**kwargs), None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=20.0),
        dry_run=True,
    )

    assert decision is not None
    assert decision.direction == "USDC_TO_EQUITY"
    # Execution uses plan size capped by USDC (fixed-sizing tier override removed 2026-05-03).
    assert decision.trade_size == 20.0
    assert decision.amount_in == int(20.0 * 1_000_000)


def test_try_x_signal_equity_decision_caps_dynamic_size_to_available_usdc(monkeypatch):
    class _Plan:
        direction = "USDC_TO_EQUITY"
        amount_in = 1
        trade_size = 20.0
        message = "buy"
        token_in = "0x" + "2" * 40
        token_out = "0x" + "1" * 40

    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan(self, **kwargs):
            _ = kwargs
            return _Plan()

        def build_plan_with_block_reason(self, **kwargs):
            return self.build_plan(**kwargs), None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=8.0),
        dry_run=True,
    )

    assert decision is not None
    assert decision.direction == "USDC_TO_EQUITY"
    assert decision.trade_size == 8.0
    assert decision.amount_in == int(8.0 * 1_000_000)


def test_try_x_signal_logs_balance_source_and_prefers_onchain_usdc(monkeypatch, capsys):
    class _Plan:
        direction = "USDC_TO_EQUITY"
        amount_in = 1
        trade_size = 20.0
        message = "buy"
        token_in = "0x" + "2" * 40
        token_out = "0x" + "1" * 40

    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def __init__(self):
            self.last_usdc_balance_source = "not_queried"

        def _query_onchain_usdc_balance(self, fallback):
            _ = fallback
            self.last_usdc_balance_source = "onchain"
            return 40.0

        def build_plan(self, **kwargs):
            _ = kwargs
            return _Plan()

        def build_plan_with_block_reason(self, **kwargs):
            return self.build_plan(**kwargs), None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.92,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=5.0),
        dry_run=True,
    )
    out = capsys.readouterr().out

    assert decision is not None
    assert decision.direction == "USDC_TO_EQUITY"
    assert decision.trade_size == 20.0
    assert "USDC BALANCE SOURCE | source=onchain" in out


def test_sorted_and_eligible_equities_respects_per_asset_min_signal_strength():
    assets = [
        clean_swap.FollowedEquity(
            symbol="USDC",
            token_address="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            decimals=6,
            signal_strength=0.76,
            min_signal_strength=0.75,
        ),
        clean_swap.FollowedEquity(
            symbol="WETH",
            token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
            decimals=18,
            signal_strength=0.72,
            min_signal_strength=0.75,
        ),
    ]

    _all_assets, eligible = clean_swap._sorted_and_eligible_equities(
        assets, min_strength=0.60, strong_threshold=0.80
    )

    assert [a.symbol for a in eligible] == ["USDC"]


def test_sorted_and_eligible_equities_allows_strong_asset_above_global_threshold_even_when_per_asset_floor_is_higher():
    assets = [
        clean_swap.FollowedEquity(
            symbol="WETH",
            token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
            decimals=18,
            signal_strength=0.81,
            min_signal_strength=0.87,
        ),
        clean_swap.FollowedEquity(
            symbol="LINK",
            token_address="0x53e0bca35ec356bd5dddfebbd1fc0fd03fabad39",
            decimals=18,
            signal_strength=0.79,
            min_signal_strength=0.70,
        ),
    ]

    _all_assets, eligible = clean_swap._sorted_and_eligible_equities(
        assets, min_strength=0.60, strong_threshold=0.80
    )

    assert [a.symbol for a in eligible] == ["WETH", "LINK"]


def test_sorted_and_eligible_equities_respects_explicit_zero_floor():
    assets = [
        clean_swap.FollowedEquity(
            symbol="ZERO_FLOOR",
            token_address="0x1111111111111111111111111111111111111111",
            decimals=18,
            signal_strength=0.10,
            min_signal_strength=0.0,
        ),
    ]

    _all_assets, eligible = clean_swap._sorted_and_eligible_equities(
        assets, min_strength=0.60, strong_threshold=0.80
    )

    assert [a.symbol for a in eligible] == ["ZERO_FLOOR"]


def test_sorted_and_eligible_equities_force_eligible_threshold_below_strong_threshold():
    """0.79 can qualify via force_eligible when strong_bar is 0.80."""
    assets = [
        clean_swap.FollowedEquity(
            symbol="LINK",
            token_address="0x1111111111111111111111111111111111111111",
            decimals=18,
            signal_strength=0.79,
        ),
    ]
    _, eligible = clean_swap._sorted_and_eligible_equities(
        assets,
        min_strength=0.60,
        strong_threshold=0.80,
        force_eligible_threshold=0.78,
    )
    assert [a.symbol for a in eligible] == ["LINK"]


def test_evaluate_x_signal_equity_trade_returns_none_after_eligible_loop(monkeypatch):
    from nanoclaw.strategies.signal_equity_trader import EquityTradePlan

    class _Cfg:
        strong_signal_threshold = 0.80
        force_high_conviction = True
        high_conviction_threshold = 0.80
        force_eligible_threshold = 0.80

    class _Trader:
        config = _Cfg()

        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WETH",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.87,
                )
            ]

    expected = EquityTradePlan(
        direction="USDC_TO_EQUITY",
        symbol="WETH",
        token_in="0x" + "2" * 40,
        token_out="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in=10_000_000,
        trade_size=10.0,
        message="ok",
        signal_strength=0.87,
    )

    class _Tuned:
        config = type("_TC", (), {"per_asset_cooldown_seconds": 1800})()

        def build_plan(self, **kwargs):
            _ = kwargs
            return expected

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _Tuned())

    out = clean_swap.evaluate_x_signal_equity_trade(
        clean_swap.Balances(usdt=1.0, wmatic=1.0, pol=1.0, usdc=50.0),
        trader=_Trader(),
    )
    assert out is None


def test_evaluate_x_signal_equity_trade_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", False)

    class _T:
        config = None

        def load_followed_equities(self):
            return []

    assert clean_swap.evaluate_x_signal_equity_trade(clean_swap.Balances(1, 1, 1, 1), trader=_T()) is None


def test_order_eligible_x_signal_candidates_prefers_tradable_over_higher_signal_on_cooldown(monkeypatch):
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT", True)

    wmatic = clean_swap.FollowedEquity(
        symbol="WMATIC_ALPHA",
        token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        decimals=18,
        signal_strength=0.92,
    )
    weth = clean_swap.FollowedEquity(
        symbol="WETH_ALPHA",
        token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        signal_strength=0.87,
    )

    def fake_can_trade(sym: str, now=None, cooldown_seconds=0):
        return sym != "WMATIC_ALPHA"

    monkeypatch.setattr(clean_swap, "can_trade_asset", fake_can_trade)
    out = clean_swap._order_eligible_x_signal_candidates(
        [wmatic, weth],
        per_asset_cooldown_seconds=1800,
    )
    assert [a.symbol for a in out] == ["WETH_ALPHA", "WMATIC_ALPHA"]


def test_order_eligible_x_signal_legacy_pure_signal_when_sort_disabled(monkeypatch):
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT", False)

    wmatic = clean_swap.FollowedEquity(
        symbol="WMATIC_ALPHA",
        token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        decimals=18,
        signal_strength=0.92,
    )
    weth = clean_swap.FollowedEquity(
        symbol="WETH_ALPHA",
        token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        signal_strength=0.87,
    )

    def fake_can_trade(sym: str, now=None, cooldown_seconds=0):
        return sym != "WMATIC_ALPHA"

    monkeypatch.setattr(clean_swap, "can_trade_asset", fake_can_trade)
    out = clean_swap._order_eligible_x_signal_candidates(
        [wmatic, weth],
        per_asset_cooldown_seconds=1800,
    )
    assert [a.symbol for a in out] == ["WMATIC_ALPHA", "WETH_ALPHA"]


def test_try_x_signal_equity_prioritizes_ready_asset_sorted_before_build_plan(monkeypatch):
    class _Plan:
        direction = "USDC_TO_EQUITY"
        amount_in = 8_000_000
        trade_size = 8.0
        message = "buy"
        token_in = "0x" + "2" * 40
        token_out = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"

    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    build_order: list[str] = []

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan_with_block_reason(self, **kwargs):
            sym = str(kwargs.get("symbol", "")).strip()
            build_order.append(sym)
            if sym == "WMATIC_ALPHA":
                return None, "per_asset_cooldown_stub"
            return _Plan(), None

        def build_plan(self, **kwargs):
            p, _ = self.build_plan_with_block_reason(**kwargs)
            return p

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                ),
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.87,
                ),
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "AUTO_TOPUP_POL", False)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())

    def fake_can_trade(sym: str, now=None, cooldown_seconds=0):
        return sym != "WMATIC_ALPHA"

    monkeypatch.setattr(clean_swap, "can_trade_asset", fake_can_trade)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_a, **_k: 0.0)

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=20.0),
        dry_run=True,
    )

    assert decision is not None
    assert decision.direction == "USDC_TO_EQUITY"
    assert build_order[0] == "WETH_ALPHA"


def test_try_x_signal_high_conviction_bypasses_high_gas_and_forces_usdc_topup(monkeypatch, capsys):
    class _Plan:
        direction = "USDC_TO_EQUITY"
        amount_in = 1
        trade_size = 5.0
        message = "buy"
        token_in = "0x" + "2" * 40
        token_out = "0x" + "1" * 40

    class _GasProtectorHighGas:
        def get_safe_status(self, address, urgent=False, min_pol=None):
            _ = (address, urgent, min_pol)
            return {
                "gas_ok": False,
                "pol_balance": 1.0,
                "gas_gwei": 614.11,
                "max_gwei": 450.0,
            }

    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    captured_kwargs = {}

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _GasProtectorHighGas()

        def build_plan(self, **kwargs):
            captured_kwargs.update(kwargs)
            return _Plan()

        def build_plan_with_block_reason(self, **kwargs):
            return self.build_plan(**kwargs), None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                ),
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.87,
                ),
            ]

    usdc_topup_calls = []

    def _ensure_usdc_for_x_signal(min_usdc, min_wmatic_value, force=False):
        _ = force
        usdc_topup_calls.append((float(min_usdc), float(min_wmatic_value)))

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "AUTO_TOPUP_POL", False)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(clean_swap, "ensure_usdc_for_x_signal", _ensure_usdc_for_x_signal)
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
    )

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
        dry_run=False,
    )

    out = capsys.readouterr().out
    assert decision is not None
    assert decision.direction == "USDC_TO_EQUITY"
    assert captured_kwargs.get("allow_high_gas_override") is True
    assert usdc_topup_calls == [(25.0, 15.0)]
    assert "🚀 HIGH-CONVICTION MODE ACTIVE" in out
    assert "🚀 HIGH-CONVICTION GAS OVERRIDE" in out
    assert "gas blocked (gas≈" not in out


def test_try_x_signal_high_conviction_no_plan_logs_override_not_gas_blocked(monkeypatch, capsys):
    class _GasProtectorHighGas:
        def get_safe_status(self, address, urgent=False, min_pol=None):
            _ = (address, urgent, min_pol)
            return {
                "gas_ok": False,
                "pol_balance": 1.0,
                "gas_gwei": 614.11,
                "max_gwei": 450.0,
            }

    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _GasProtectorHighGas()

        def build_plan(self, **kwargs):
            _ = kwargs
            return None

        def build_plan_with_block_reason(self, **kwargs):
            _ = kwargs
            return None, "mock_no_plan"

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "AUTO_TOPUP_POL", False)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=20.0),
        dry_run=True,
    )

    out = capsys.readouterr().out
    assert decision is None
    thr = clean_swap.X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD
    assert (
        f"gas override active ({thr:.2f}+ high conviction; bypassing {clean_swap.MAX_GWEI:.0f} gwei block)"
        in out
    )
    assert "gas blocked (gas≈" not in out


def test_try_x_signal_does_not_log_high_conviction_when_followed_equities_disabled(monkeypatch, capsys):
    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": False, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=20.0),
        dry_run=True,
    )

    out = capsys.readouterr().out
    assert decision is None
    assert "followed_equities disabled" in out
    assert "🚀 HIGH-CONVICTION MODE ACTIVE" not in out


def test_try_x_signal_logs_high_conviction_auto_usdc_failure(monkeypatch, capsys):
    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan(self, **kwargs):
            _ = kwargs
            return None

        def build_plan_with_block_reason(self, **kwargs):
            return self.build_plan(**kwargs), None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WMATIC_ALPHA",
                    token_address="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
                    decimals=18,
                    signal_strength=0.92,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "AUTO_TOPUP_POL", False)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(clean_swap, "ensure_usdc_for_x_signal", lambda min_usdc, min_wmatic_value, force=False: False)
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
    )

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
        dry_run=False,
    )

    out = capsys.readouterr().out
    assert decision is None
    assert "AUTO-USDC top-up attempted but floor not reached" in out


def test_try_x_signal_skips_auto_topup_when_flag_disabled(monkeypatch):
    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan_with_block_reason(self, **kwargs):
            _ = kwargs
            return None, "mock_no_plan"

        def build_plan(self, **kwargs):
            _ = kwargs
            return None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.90,
                )
            ]

    calls = {"count": 0}

    def _ensure(*_args, **_kwargs):
        calls["count"] += 1
        return False

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", False)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(clean_swap, "ensure_usdc_for_x_signal", _ensure)

    clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
        dry_run=False,
    )

    assert calls["count"] == 0


def test_try_x_signal_auto_topup_skips_when_buy_asset_on_cooldown(monkeypatch):
    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan_with_block_reason(self, **kwargs):
            _ = kwargs
            return None, "mock_no_plan"

        def build_plan(self, **kwargs):
            _ = kwargs
            return None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.74,
                )
            ]

    calls = {"count": 0}

    def _ensure(*_args, **_kwargs):
        calls["count"] += 1
        return False

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: False)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(clean_swap, "ensure_usdc_for_x_signal", _ensure)
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
    )

    clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
        dry_run=False,
    )

    assert calls["count"] == 0


def test_try_x_signal_auto_topup_runs_when_high_conviction_even_if_cooldown_blocked(monkeypatch):
    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan_with_block_reason(self, **kwargs):
            _ = kwargs
            return None, "mock_no_plan"

        def build_plan(self, **kwargs):
            _ = kwargs
            return None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.91,
                )
            ]

    calls = {"count": 0}

    def _ensure(*_args, **_kwargs):
        calls["count"] += 1
        return False

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: False)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(clean_swap, "ensure_usdc_for_x_signal", _ensure)
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
    )

    clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
        dry_run=False,
    )

    assert calls["count"] == 1


def test_try_x_signal_logs_auto_topup_consideration(monkeypatch, capsys):
    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan_with_block_reason(self, **kwargs):
            _ = kwargs
            return None, "mock_no_plan"

        def build_plan(self, **kwargs):
            _ = kwargs
            return None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.91,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: False)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(clean_swap, "ensure_usdc_for_x_signal", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
    )

    clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
        dry_run=False,
    )

    out = capsys.readouterr().out
    assert "AUTO-USDC consider" in out


def test_try_x_signal_logs_standard_auto_usdc_failure(monkeypatch, capsys):
    class _TunedConfig:
        min_trade_usdc = 5.0
        per_asset_cooldown_seconds = 1800
        min_pol_for_gas = 0.005

    class _TunedTrader:
        config = _TunedConfig()
        gas_protector = _DummyGasProtector()

        def build_plan(self, **kwargs):
            _ = kwargs
            return None

        def build_plan_with_block_reason(self, **kwargs):
            return self.build_plan(**kwargs), None

    class _BaseTrader:
        def load_followed_equities(self):
            return [
                clean_swap.FollowedEquity(
                    symbol="WETH_ALPHA",
                    token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                    decimals=18,
                    signal_strength=0.75,
                )
            ]

    monkeypatch.setattr(clean_swap, "ENABLE_X_SIGNAL_EQUITY", True)
    monkeypatch.setattr(clean_swap, "AUTO_TOPUP_POL", False)
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "_effective_equity_signal_min", lambda cfg: 0.60)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _BaseTrader())
    monkeypatch.setattr(clean_swap, "_tuned_signal_equity_trader", lambda min_strength: _TunedTrader())
    monkeypatch.setattr(clean_swap, "can_trade_asset", lambda symbol, now=None, cooldown_seconds=0: True)
    monkeypatch.setattr(clean_swap, "get_token_balance", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(clean_swap, "ensure_usdc_for_x_signal", lambda min_usdc, min_wmatic_value, force=False: False)
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
    )

    decision = clean_swap.try_x_signal_equity_decision(
        clean_swap.Balances(usdt=40.0, wmatic=10.0, pol=1.0, usdc=2.0),
        dry_run=False,
    )

    out = capsys.readouterr().out
    assert decision is None
    assert "Auto-USDC attempt failed (guard/tx) — BUY paths may be skipped" not in out
    assert "Auto-USDC failed during HIGH-CONVICTION prep" not in out


# --- clean_swap helper coverage (load JSON, USDC projection, strong-buy gate, copy-trade) ---


def _gas_status_ok() -> dict:
    return {"ok": True, "gas_ok": True, "pol_balance": 1.0, "gas_gwei": 20.0, "max_gwei": 80.0}


class _GasProtectorOk:
    def get_safe_status(self, **kwargs):
        return _gas_status_ok()


class _GasProtectorBad:
    def get_safe_status(self, **kwargs):
        return {"ok": False, "gas_ok": False, "pol_balance": 0.0}


def test_load_followed_equities_json_dict_empty_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(clean_swap, "FOLLOWED_EQUITIES_PATH", str(tmp_path / "missing.json"))
    assert clean_swap._load_followed_equities_json_dict() == {}


def test_load_followed_equities_json_dict_empty_on_invalid_json(monkeypatch, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(clean_swap, "FOLLOWED_EQUITIES_PATH", str(p))
    assert clean_swap._load_followed_equities_json_dict() == {}


def test_load_followed_equities_json_dict_empty_when_root_not_dict(monkeypatch, tmp_path):
    p = tmp_path / "list.json"
    p.write_text(json.dumps([1, 2]), encoding="utf-8")
    monkeypatch.setattr(clean_swap, "FOLLOWED_EQUITIES_PATH", str(p))
    assert clean_swap._load_followed_equities_json_dict() == {}


def test_effective_floor_for_equity_prefers_per_asset_floor():
    with_floor = clean_swap.FollowedEquity(
        symbol="X",
        token_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        decimals=18,
        signal_strength=0.5,
        min_signal_strength=0.88,
    )
    assert clean_swap._effective_floor_for_equity(with_floor, 0.60) == 0.88
    base_only = clean_swap.FollowedEquity(
        symbol="Y",
        token_address="0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        decimals=18,
        signal_strength=0.5,
    )
    assert clean_swap._effective_floor_for_equity(base_only, 0.60) == 0.60


def test_reconcile_total_portfolio_with_onchain_adjusts_only_when_populated():
    from modules import signal as signal_module

    adjusted = signal_module._reconcile_total_portfolio_usd_with_onchain_usdc(
        total_portfolio_usd=250.0,
        snapshot_usdc=100.0,
        onchain_preferred_usdc=120.0,
    )
    assert adjusted == 270.0

    uninitialized = signal_module._reconcile_total_portfolio_usd_with_onchain_usdc(
        total_portfolio_usd=0.0,
        snapshot_usdc=100.0,
        onchain_preferred_usdc=120.0,
    )
    assert uninitialized == 20.0

    negative_total = signal_module._reconcile_total_portfolio_usd_with_onchain_usdc(
        total_portfolio_usd=-10.0,
        snapshot_usdc=100.0,
        onchain_preferred_usdc=140.0,
    )
    assert negative_total == 30.0


def test_effective_equity_signal_min_uses_env_when_json_floor_lower(monkeypatch):
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_MIN_STRENGTH", 0.72)
    assert clean_swap._effective_equity_signal_min({"min_signal_strength": 0.50}) == 0.72


def test_strong_x_signal_buy_present_false_when_json_disabled(monkeypatch):
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": False})
    assert clean_swap._strong_x_signal_buy_present() is False


def test_strong_x_signal_buy_present_true_when_eligible_buy(monkeypatch):
    asset = clean_swap.FollowedEquity(
        symbol="WETH",
        token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        signal_strength=0.85,
    )

    class _T:
        def load_followed_equities(self):
            return [asset]

    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _T())
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})
    monkeypatch.setattr(clean_swap, "X_SIGNAL_STRONG_THRESHOLD", 0.80)
    assert clean_swap._strong_x_signal_buy_present() is True


def test_strong_x_signal_buy_present_false_when_signal_below_strong_bar(monkeypatch):
    asset = clean_swap.FollowedEquity(
        symbol="LINK",
        token_address="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03fabad39",
        decimals=18,
        signal_strength=0.72,
    )

    class _T:
        def load_followed_equities(self):
            return [asset]

    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _T())
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True})
    monkeypatch.setattr(clean_swap, "X_SIGNAL_STRONG_THRESHOLD", 0.80)
    assert clean_swap._strong_x_signal_buy_present() is False


def test_strong_x_signal_buy_present_false_for_negative_signal(monkeypatch):
    asset = clean_swap.FollowedEquity(
        symbol="WETH",
        token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        signal_strength=-0.90,
    )

    class _T:
        def load_followed_equities(self):
            return [asset]

    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _T())
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True})
    monkeypatch.setattr(clean_swap, "X_SIGNAL_STRONG_THRESHOLD", 0.80)
    assert clean_swap._strong_x_signal_buy_present() is False


def test_project_balances_after_auto_usdc_unchanged_when_already_funded():
    b = clean_swap.Balances(usdt=0.0, wmatic=0.0, pol=1.0, usdc=100.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out == b


def test_project_balances_after_auto_usdc_unchanged_without_strong_buy(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: False)
    b = clean_swap.Balances(usdt=0.0, wmatic=10.0, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out.usdc == 5.0


def test_project_balances_after_auto_usdc_unchanged_when_gas_bad(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorBad())
    b = clean_swap.Balances(usdt=0.0, wmatic=10.0, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out.usdc == 5.0


def test_project_balances_after_auto_usdc_unchanged_without_private_key(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    b = clean_swap.Balances(usdt=0.0, wmatic=10.0, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out.usdc == 5.0


def test_project_balances_after_auto_usdc_unchanged_when_price_unavailable(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    def _bad_price() -> float:
        raise RuntimeError("rpc")

    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", _bad_price)
    b = clean_swap.Balances(usdt=0.0, wmatic=10.0, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out.usdc == 5.0


def test_project_balances_after_auto_usdc_unchanged_when_wmatic_price_nonpositive(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 0.0)
    b = clean_swap.Balances(usdt=0.0, wmatic=10.0, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out.usdc == 5.0


def test_project_balances_after_auto_usdc_projects_wmatic_to_usdc(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    # USDC 10 + ~42 projected from WMATIC reaches min_usdc 50
    b = clean_swap.Balances(usdt=0.0, wmatic=25.0, pol=1.0, usdc=10.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out.usdc >= 50.0
    assert out.wmatic < b.wmatic


def test_project_balances_after_auto_usdc_usdt_fallback_path(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    # Low WMATIC USD but enough USDT to project USDC (non-WMATIC-first branch)
    b = clean_swap.Balances(usdt=80.0, wmatic=1.0, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)
    assert out.usdc >= 50.0
    assert out.usdt < b.usdt


def test_project_balances_after_auto_usdc_preserves_portfolio_fields(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)

    b = clean_swap.Balances(
        usdt=80.0,
        wmatic=1.0,
        pol=1.0,
        usdc=5.0,
        followed_equity_usd=17.5,
        total_portfolio_usd=123.45,
    )
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=50.0, min_wmatic_value=15.0)

    assert out.usdc >= 50.0
    assert out.followed_equity_usd == b.followed_equity_usd
    assert out.total_portfolio_usd == b.total_portfolio_usd


def test_project_balances_after_auto_usdc_wmatic_partial_then_usdt(monkeypatch):
    """WMATIC leg alone does not hit ``min_usdc``; USDT branch completes projection."""
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    # Force-eligible strong-buy projection: WMATIC swap closes most but not all of the gap to min_usdc.
    b = clean_swap.Balances(usdt=120.0, wmatic=20.0, pol=1.0, usdc=40.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=100.0, min_wmatic_value=15.0)
    assert out.usdc >= 100.0
    assert out.usdt < b.usdt


def test_project_balances_after_auto_usdc_unable_to_reach_target_returns_input(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    b = clean_swap.Balances(usdt=0.01, wmatic=0.001, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=500.0, min_wmatic_value=15.0)
    assert out == b


def test_project_balances_after_auto_usdc_wmatic_block_then_insufficient_usdt_returns_input(monkeypatch):
    """WMATIC projection undershoots ``min_usdc`` and USDT reserve too small to close the gap."""
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    b = clean_swap.Balances(usdt=0.3, wmatic=20.0, pol=1.0, usdc=40.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=100.0, min_wmatic_value=15.0)
    assert out == b


def test_ensure_usdc_for_x_signal_true_when_balance_already_sufficient(monkeypatch):
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=0.0, wmatic=0.0, pol=1.0, usdc=100.0),
    )
    assert clean_swap.ensure_usdc_for_x_signal(min_usdc=30.0) is True


def test_ensure_usdc_for_x_signal_false_without_force_or_strong_buy(monkeypatch):
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=0.0, wmatic=0.0, pol=1.0, usdc=5.0),
    )
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: False)
    assert clean_swap.ensure_usdc_for_x_signal(min_usdc=50.0, force=False) is False


def test_ensure_usdc_for_x_signal_skipped_when_gas_not_ok(monkeypatch):
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=0.0, wmatic=0.0, pol=1.0, usdc=5.0),
    )
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorBad())
    assert clean_swap.ensure_usdc_for_x_signal(min_usdc=50.0, force=True) is False


def test_ensure_usdc_for_x_signal_skipped_without_private_key(monkeypatch):
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=0.0, wmatic=0.0, pol=1.0, usdc=5.0),
    )
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    assert clean_swap.ensure_usdc_for_x_signal(min_usdc=50.0, force=True) is False


def test_ensure_usdc_for_x_signal_skipped_when_wmatic_price_zero(monkeypatch):
    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=0.0, wmatic=10.0, pol=1.0, usdc=5.0),
    )
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 0.0)
    assert clean_swap.ensure_usdc_for_x_signal(min_usdc=50.0, force=True) is False


def test_ensure_usdc_for_x_signal_returns_early_when_topup_flag_disabled(monkeypatch, capsys):
    from modules import signal as signal_module

    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", False)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", 8.0)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: False)

    state = {"calls": 0}

    def _get_balances():
        if state["calls"] == 0:
            state["calls"] += 1
            return clean_swap.Balances(usdt=30.0, wmatic=0.0, pol=1.0, usdc=5.0)
        state["calls"] += 1
        return clean_swap.Balances(usdt=10.0, wmatic=0.0, pol=1.0, usdc=30.0)

    monkeypatch.setattr(clean_swap, "get_balances", _get_balances)

    directions: list[str] = []

    async def _fake_swap(*_args, **kwargs):
        directions.append(str(kwargs.get("direction")))
        return "0xhash"

    monkeypatch.setattr(signal_module, "approve_and_swap", _fake_swap)

    ok = clean_swap.ensure_usdc_for_x_signal(min_usdc=25.0, force=True)
    assert ok is False
    assert directions == []
    assert "AUTO-USDC consider" in capsys.readouterr().out


def test_ensure_usdc_for_x_signal_prefers_usdt_before_wmatic(monkeypatch):
    from modules import signal as signal_module

    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", 8.0)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)

    state = {"calls": 0}

    def _get_balances():
        # Initial read, then reads during/after USDT top-up path.
        if state["calls"] == 0:
            state["calls"] += 1
            return clean_swap.Balances(usdt=40.0, wmatic=50.0, pol=1.0, usdc=5.0)
        state["calls"] += 1
        return clean_swap.Balances(usdt=20.0, wmatic=50.0, pol=1.0, usdc=30.0)

    monkeypatch.setattr(clean_swap, "get_balances", _get_balances)

    directions: list[str] = []

    async def _fake_swap(*_args, **kwargs):
        directions.append(str(kwargs.get("direction")))
        return "0xhash"

    monkeypatch.setattr(signal_module, "approve_and_swap", _fake_swap)

    ok = clean_swap.ensure_usdc_for_x_signal(min_usdc=25.0, force=True)
    assert ok is True
    assert directions == ["USDT_TO_USDC"]


def test_ensure_usdc_for_x_signal_min_swap_threshold_skips_small_usdt_leg(monkeypatch):
    from modules import signal as signal_module

    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", 12.0)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)

    state = {"calls": 0}

    def _get_balances():
        if state["calls"] == 0:
            state["calls"] += 1
            return clean_swap.Balances(usdt=10.0, wmatic=20.0, pol=1.0, usdc=5.0)
        state["calls"] += 1
        return clean_swap.Balances(usdt=10.0, wmatic=10.0, pol=1.0, usdc=30.0)

    monkeypatch.setattr(clean_swap, "get_balances", _get_balances)

    directions: list[str] = []

    async def _fake_swap(*_args, **kwargs):
        directions.append(str(kwargs.get("direction")))
        return "0xhash"

    monkeypatch.setattr(signal_module, "approve_and_swap", _fake_swap)

    ok = clean_swap.ensure_usdc_for_x_signal(min_usdc=25.0, force=True)
    assert ok is True
    assert directions == ["WMATIC_TO_USDC"]


def test_ensure_usdc_for_x_signal_reports_unknown_submission_when_swap_raises(monkeypatch, capsys):
    from modules import signal as signal_module

    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", 8.0)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)

    monkeypatch.setattr(
        clean_swap,
        "get_balances",
        lambda: clean_swap.Balances(usdt=40.0, wmatic=50.0, pol=1.0, usdc=5.0),
    )

    async def _raise_on_swap(*_args, **_kwargs):
        raise RuntimeError("rpc timeout")

    monkeypatch.setattr(signal_module, "approve_and_swap", _raise_on_swap)

    ok = clean_swap.ensure_usdc_for_x_signal(min_usdc=25.0, force=True)
    out = capsys.readouterr().out
    assert ok is False
    assert "submission status unknown" in out
    assert "before submission" not in out


def test_project_balances_after_auto_usdc_respects_min_swap_threshold(monkeypatch):
    monkeypatch.setattr(clean_swap, "_strong_x_signal_buy_present", lambda: True)
    monkeypatch.setattr(clean_swap, "GAS_PROTECTOR", _GasProtectorOk())
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setattr(clean_swap, "get_live_wmatic_price", lambda: 2.0)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", 12.0)

    b = clean_swap.Balances(usdt=10.0, wmatic=0.0, pol=1.0, usdc=5.0)
    out = clean_swap._project_balances_after_auto_usdc(b, min_usdc=14.0, min_wmatic_value=15.0)
    assert out == b


def test_select_copy_trade_none_when_all_target_wallets_on_cooldown(monkeypatch):
    monkeypatch.setattr(clean_swap, "can_trade_wallet", lambda _addr: False)
    decision = clean_swap.select_copy_trade(
        clean_swap.Balances(usdt=50.0, wmatic=0.0, pol=1.0, usdc=0.0),
        ["0x1111111111111111111111111111111111111111", "0x2222222222222222222222222222222222222222"],
    )
    assert decision.should_execute is False
    assert "cooldown" in (decision.message or "").lower()
