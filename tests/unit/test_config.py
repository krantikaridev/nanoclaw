import config


def test_reconcile_fixed_trade_min_raises_strategy_floor_to_global_minimum():
    assert config.reconcile_fixed_trade_min(6.5, 5.0) == 6.5


def test_reconcile_fixed_trade_min_keeps_higher_strategy_floor():
    assert config.reconcile_fixed_trade_min(6.5, 9.0) == 9.0


def test_env_float_uses_default_when_value_is_empty(monkeypatch):
    monkeypatch.setenv("TEST_ENV_FLOAT_EMPTY", "")
    assert config.env_float("TEST_ENV_FLOAT_EMPTY", 5.0) == 5.0


def test_env_int_uses_default_when_value_is_empty(monkeypatch):
    monkeypatch.setenv("TEST_ENV_INT_EMPTY", "")
    assert config.env_int("TEST_ENV_INT_EMPTY", 7) == 7


def test_env_bool_uses_default_when_value_is_empty(monkeypatch):
    monkeypatch.setenv("TEST_ENV_BOOL_EMPTY", "")
    assert config.env_bool("TEST_ENV_BOOL_EMPTY", True) is True
