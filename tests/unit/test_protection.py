import json

import protection


def test_check_exit_conditions_triggers_fluctuation(monkeypatch):
    monkeypatch.setattr(protection, "get_balances", lambda: (20.0, 80.0))

    should_exit, reason = protection.check_exit_conditions()

    assert should_exit is True
    assert reason == "FLUCTUATION"


def test_check_exit_conditions_returns_false_when_no_trade_log(monkeypatch):
    monkeypatch.setattr(protection, "get_balances", lambda: (60.0, 20.0))
    monkeypatch.setattr(protection.os.path, "exists", lambda _path: False)

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
