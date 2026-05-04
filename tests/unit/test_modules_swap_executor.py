from modules.runtime import TradeDecision
from modules.swap_executor import _decision_notional_usd


def test_decision_notional_usd_prefers_explicit_trade_size():
    d = TradeDecision(direction="USDT_TO_WMATIC", amount_in=1, trade_size=27.5)
    assert _decision_notional_usd(d, current_price_usd=0.0) == 27.5


def test_decision_notional_usd_converts_stable_input_amount_in_6_decimals():
    d = TradeDecision(direction="USDC_TO_EQUITY", amount_in=4_500_000)
    assert _decision_notional_usd(d, current_price_usd=0.0) == 4.5


def test_decision_notional_usd_converts_wmatic_input_amount_in_18_decimals():
    d = TradeDecision(direction="WMATIC_TO_USDT", amount_in=int(8 * 1_000_000_000_000_000_000))
    assert _decision_notional_usd(d, current_price_usd=2.0) == 16.0


def test_decision_notional_usd_returns_none_for_wmatic_input_when_price_missing():
    d = TradeDecision(direction="WMATIC_TO_USDT", amount_in=int(8 * 1_000_000_000_000_000_000))
    assert _decision_notional_usd(d, current_price_usd=0.0) is None
