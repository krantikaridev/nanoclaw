import config


def test_reconcile_fixed_trade_min_raises_strategy_floor_to_global_minimum():
    assert config.reconcile_fixed_trade_min(6.5, 5.0) == 6.5


def test_reconcile_fixed_trade_min_keeps_higher_strategy_floor():
    assert config.reconcile_fixed_trade_min(6.5, 9.0) == 9.0
