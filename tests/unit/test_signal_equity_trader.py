import json

from nanoclaw.strategies.signal_equity_trader import SignalEquityTrader
from nanoclaw.utils.gas_protector import GasProtector


class DummyProtector(GasProtector):
    def __init__(self, *, gas_ok: bool, pol_balance: float) -> None:
        self._gas_ok = gas_ok
        self._pol_balance = pol_balance

    def get_safe_status(self, address: str, urgent: bool = False, min_pol: float | None = None) -> dict:  # type: ignore[override]
        return {
            "ok": self._gas_ok and self._pol_balance >= float(min_pol or 0.0),
            "gas_ok": self._gas_ok,
            "pol_balance": self._pol_balance,
            "gas_gwei": 50.0,
            "max_gwei": 80.0,
            "min_pol_balance": float(min_pol or 0.0),
        }


def _build_strategy(*, gas_ok: bool, pol_balance: float) -> SignalEquityTrader:
    return (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_gas_protector(DummyProtector(gas_ok=gas_ok, pol_balance=pol_balance))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )


def test_build_plan_blocks_when_fresh_pol_from_gas_guard_is_low():
    strategy = _build_strategy(gas_ok=True, pol_balance=0.0)

    plan = strategy.build_plan(
        symbol="WMATIC_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.23,
        usdc_balance=100.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
    )

    assert plan is None


def test_build_plan_uses_fresh_guard_pol_and_builds_buy_when_sufficient():
    strategy = _build_strategy(gas_ok=True, pol_balance=1.0)

    plan = strategy.build_plan(
        symbol="WMATIC_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.23,
        usdc_balance=100.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
    )

    assert plan is not None
    assert plan.direction == "USDC_TO_EQUITY"


def test_build_plan_allows_high_gas_when_override_enabled():
    strategy = _build_strategy(gas_ok=False, pol_balance=1.0)

    plan = strategy.build_plan(
        symbol="WMATIC_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.23,
        usdc_balance=100.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
        allow_high_gas_override=True,
    )

    assert plan is not None
    assert plan.direction == "USDC_TO_EQUITY"


def test_load_followed_equities_keeps_per_asset_min_signal_strength(tmp_path):
    followed_path = tmp_path / "followed_equities.json"
    followed_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "assets": [
                    {
                        "symbol": "USDC",
                        "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
                        "decimals": 6,
                        "signal_strength": 0.80,
                        "min_signal_strength": 0.75,
                    },
                    {
                        "symbol": "WETH",
                        "address": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                        "decimals": 18,
                        "signal_strength": 0.72,
                        "min_signal_strength": 0.70,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    strategy = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_followed_equities_path(str(followed_path))
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )

    assets = strategy.load_followed_equities()

    assert len(assets) == 2
    assert assets[0].symbol == "USDC"
    assert assets[0].min_signal_strength == 0.75
    assert assets[1].symbol == "WETH"
    assert assets[1].min_signal_strength == 0.70


def test_buy_usdc_same_as_reserve_is_usdc_identity_noop():
    usdc_polygon = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    strategy = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address(usdc_polygon)
        .build()
    )

    plan, reason = strategy.build_plan_with_block_reason(
        symbol="USDC",
        token_address=usdc_polygon.upper(),
        token_decimals=6,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
    )
    assert plan is None
    assert reason == "usdc_identity_noop"


def test_below_strong_signal_threshold_returns_explained_reason():
    strategy = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_strong_signal_threshold(0.90)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )

    _, reason = strategy.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.85,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
    )
    assert reason is not None and "below_strong_threshold" in reason
