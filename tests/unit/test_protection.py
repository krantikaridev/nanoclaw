import json

import protection


def test_check_exit_conditions_suppresses_fluctuation_within_cooldown(monkeypatch, tmp_path):
    monkeypatch.setattr(protection, "TRADE_LOG_FILE", str(tmp_path / "missing_trade_exits.json"))
    monkeypatch.setattr(protection, "get_balances", lambda: (20.0, 80.0))
    monkeypatch.setattr(protection, "get_live_wmatic_price", lambda: 1.0)
    monkeypatch.setattr(protection, "FLUCTUATION_MIN_SELL_USD", 0.0)
    monkeypatch.setattr(protection, "FLUCTUATION_COOLDOWN_SECONDS", 1800)
    monkeypatch.setattr(protection, "_last_fluctuation_trigger_ts", None)
    monkeypatch.setattr(protection, "_last_fluctuation_context", {})
    fake_times = iter([1_000.0, 1_001.0])
    monkeypatch.setattr(protection.time, "time", lambda: next(fake_times))

    should_exit, reason = protection.check_exit_conditions()
    assert should_exit is True
    assert reason == "FLUCTUATION"

    should_exit2, reason2 = protection.check_exit_conditions()
    assert should_exit2 is False
    assert reason2 is None


def test_check_exit_conditions_triggers_fluctuation(monkeypatch):
    monkeypatch.setattr(protection, "get_balances", lambda: (20.0, 80.0))
    monkeypatch.setattr(protection, "get_live_wmatic_price", lambda: 1.0)
    monkeypatch.setattr(protection, "FLUCTUATION_MIN_SELL_USD", 0.0)
    monkeypatch.setattr(protection, "_last_fluctuation_trigger_ts", None)
    monkeypatch.setattr(protection, "_last_fluctuation_context", {})

    should_exit, reason = protection.check_exit_conditions()

    assert should_exit is True
    assert reason == "FLUCTUATION"


def test_check_exit_conditions_returns_false_when_no_trade_log(monkeypatch):
    monkeypatch.setattr(protection, "get_balances", lambda: (60.0, 20.0))
    monkeypatch.setattr(protection.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(protection, "_last_fluctuation_trigger_ts", None)
    monkeypatch.setattr(protection, "_last_fluctuation_context", {})

    should_exit, reason = protection.check_exit_conditions()

    assert should_exit is False
    assert reason is None


def test_check_exit_conditions_suppresses_small_notional_fluctuation(monkeypatch, tmp_path):
    monkeypatch.setattr(protection, "TRADE_LOG_FILE", str(tmp_path / "missing_trade_exits.json"))
    monkeypatch.setattr(protection, "get_balances", lambda: (20.0, 52.0))
    monkeypatch.setattr(protection, "get_live_wmatic_price", lambda: 0.50)
    monkeypatch.setattr(protection, "FLUCTUATION_MIN_SELL_USD", 10.0)
    monkeypatch.setattr(protection, "_last_fluctuation_trigger_ts", None)
    monkeypatch.setattr(protection, "_last_fluctuation_context", {})

    should_exit, reason = protection.check_exit_conditions()

    assert should_exit is False
    assert reason is None


def test_check_exit_conditions_triggers_per_trade_exit(monkeypatch, tmp_path):
    trade_log = tmp_path / "trade_exits.json"
    trade_log.write_text(
        json.dumps(
            [
                {
                    "status": "OPEN",
                    "buy_price": 1.0,
                    "target_price": 1.08,
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(protection, "TRADE_LOG_FILE", str(trade_log))
    monkeypatch.setattr(protection, "get_balances", lambda: (60.0, 20.0))
    monkeypatch.setattr(protection, "get_live_wmatic_price", lambda: 1.10)
    monkeypatch.setattr(protection, "_last_fluctuation_trigger_ts", None)
    monkeypatch.setattr(protection, "_last_fluctuation_context", {})

    should_exit, reason = protection.check_exit_conditions()

    assert should_exit is True
    assert reason == "PER_TRADE_EXIT"


def test_check_exit_conditions_allows_per_trade_exit_when_fluctuation_suppressed(monkeypatch, tmp_path):
    trade_log = tmp_path / "trade_exits.json"
    trade_log.write_text(
        json.dumps(
            [
                {
                    "status": "OPEN",
                    "buy_price": 1.0,
                    "target_price": 1.08,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(protection, "TRADE_LOG_FILE", str(trade_log))
    monkeypatch.setattr(protection, "get_balances", lambda: (20.0, 80.0))
    monkeypatch.setattr(protection, "get_live_wmatic_price", lambda: 1.10)
    monkeypatch.setattr(protection, "FLUCTUATION_MIN_SELL_USD", 999.0)
    monkeypatch.setattr(protection, "_last_fluctuation_trigger_ts", None)
    monkeypatch.setattr(protection, "_last_fluctuation_context", {})

    should_exit, reason = protection.check_exit_conditions()

    assert should_exit is True
    assert reason == "PER_TRADE_EXIT"


def test_record_buy_writes_open_trade_with_target_price(monkeypatch, tmp_path):
    trade_log = tmp_path / "trade_exits.json"
    monkeypatch.setattr(protection, "TRADE_LOG_FILE", str(trade_log))

    protection.record_buy(1.0, 25.0, "0xabc")

    payload = json.loads(trade_log.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["status"] == "OPEN"
    assert payload[0]["buy_price"] == 1.0
    assert payload[0]["target_price"] == 1.08


def test_check_exit_conditions_tracks_notional_in_fluctuation_context(monkeypatch):
    monkeypatch.setattr(protection, "get_balances", lambda: (20.0, 80.0))
    monkeypatch.setattr(protection, "get_live_wmatic_price", lambda: 0.9)
    monkeypatch.setattr(protection, "FLUCTUATION_MIN_SELL_USD", 8.0)
    monkeypatch.setattr(protection, "_last_fluctuation_trigger_ts", None)
    monkeypatch.setattr(protection, "_last_fluctuation_context", {})

    should_exit, reason = protection.check_exit_conditions()

    assert should_exit is True
    assert reason == "FLUCTUATION"
    context = protection.get_last_fluctuation_context()
    assert context["sell_fraction"] == protection.PROTECTION_FLUCTUATION_SELL_FRACTION
    assert context["sell_notional_usd"] == 18.0
    assert context["min_sell_usd"] == 8.0
