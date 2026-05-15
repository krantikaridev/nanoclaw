import json

import pytest

from nanoclaw.strategies import signal_equity_trader as strategy_module
from nanoclaw.strategies.signal_equity_trader import SignalEquityTrader
from nanoclaw.utils.gas_protector import GasProtector

USDC_E_TEST = "0x" + "2" * 40
USDC_NATIVE_TEST = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"


def _pin_usdc_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bridged: str = USDC_E_TEST,
    native: str | None = None,
) -> None:
    monkeypatch.setenv("WALLET", "0x" + "3" * 40)
    monkeypatch.setenv("USDC", bridged)
    monkeypatch.setenv("USDC_NATIVE", native if native is not None else bridged)


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
        .with_min_trade_usdc(4.0)
        .with_gas_protector(DummyProtector(gas_ok=gas_ok, pol_balance=pol_balance))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )


def _build_strategy_tuned(
    *,
    gas_ok: bool = True,
    pol_balance: float = 1.0,
    force_eligible_threshold: float = 0.80,
    strong_signal_threshold: float = 0.80,
    max_earnings_days: float = 5.0,
    min_trade_usdc: float = 5.0,
    max_trade_usdc: float = 28.0,
) -> SignalEquityTrader:
    return (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_force_eligible_threshold(force_eligible_threshold)
        .with_strong_signal_threshold(strong_signal_threshold)
        .with_max_earnings_days(max_earnings_days)
        .with_min_trade_usdc(min_trade_usdc)
        .with_max_trade_usdc(max_trade_usdc)
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
        # Below 0.85 so POL bypass does not apply; above strong threshold so strength filter passes.
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.23,
        usdc_balance=100.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
    )

    assert plan is None


def test_build_plan_bypasses_pol_when_high_conviction_signal_over_085():
    strategy = _build_strategy(gas_ok=True, pol_balance=0.0)

    plan = strategy.build_plan(
        symbol="WMATIC_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.86,
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
                        "symbol": "LINK",
                        "address": "0x53E0bca35eC356BD5ddDFebBD1Fc0fF03FaBad39",
                        "decimals": 18,
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
    assert assets[0].symbol == "LINK"
    assert assets[0].min_signal_strength == 0.75
    assert assets[1].symbol == "WETH"
    assert assets[1].min_signal_strength == 0.70


def test_load_followed_equities_skips_reserve_usdc_row(tmp_path):
    """Reserve USDC is not an equity leg; loading must drop it to avoid noop churn."""
    followed_path = tmp_path / "followed_equities.json"
    usdc_polygon = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    followed_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "assets": [
                    {
                        "symbol": "USDC",
                        "address": usdc_polygon,
                        "decimals": 6,
                        "signal_strength": 0.9,
                    },
                    {
                        "symbol": "WETH",
                        "address": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                        "decimals": 18,
                        "signal_strength": 0.8,
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
        .with_usdc_address(usdc_polygon)
        .build()
    )
    assets = strategy.load_followed_equities()
    assert [a.symbol for a in assets] == ["WETH"]


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
        .with_force_high_conviction(False)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )

    _, reason = strategy.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.72,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
    )
    assert reason is not None and "below_strong_threshold" in reason


def test_below_threshold_is_allowed_when_force_high_conviction_true():
    strategy = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_strong_signal_threshold(0.90)
        .with_force_high_conviction(True)
        .with_min_trade_usdc(4.0)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )

    plan, reason = strategy.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda symbol, now, cooldown: True,
        now=1000.0,
    )
    assert plan is None
    assert reason == "small_trade_bypass"


def test_sorted_and_eligible_equities_keeps_high_conviction_assets(monkeypatch):
    from clean_swap import _sorted_and_eligible_equities, FollowedEquity

    assets = [
        FollowedEquity(symbol="WETH", token_address="0x" + "1" * 40, signal_strength=0.87),
        FollowedEquity(symbol="LINK", token_address="0x" + "2" * 40, signal_strength=0.79),
    ]
    eligible = _sorted_and_eligible_equities(
        assets,
        min_strength=0.80,
        strong_threshold=0.80,
        force_high_conviction=True,
    )[1]

    assert len(eligible) == 1
    assert eligible[0].symbol == "WETH"


def test_signal_equity_trader_config_builder_respects_force_high_conviction():
    strategy = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_force_high_conviction(False)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )

    assert strategy.config.force_high_conviction is False


def test_builder_raises_without_gas_protector():
    b = SignalEquityTrader.builder().with_usdc_address("0x" + "2" * 40)
    with pytest.raises(ValueError, match="GasProtector"):
        b.build()


def test_builder_raises_without_usdc_address(monkeypatch):
    monkeypatch.delenv("USDC", raising=False)
    b = SignalEquityTrader.builder().with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
    with pytest.raises(ValueError, match="USDC"):
        b.build()


def test_build_plan_returns_none_when_strategy_disabled(capsys):
    s = _build_strategy(gas_ok=True, pol_balance=1.0)
    s.config.enabled = False
    plan = s.build_plan(
        symbol="X",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert plan is None
    assert "strategy_disabled" in capsys.readouterr().out


def test_build_plan_invalid_symbol_or_token(capsys):
    s = _build_strategy(gas_ok=True, pol_balance=1.0)
    plan = s.build_plan(
        symbol="  ",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert plan is None
    assert "invalid_symbol_or_token" in capsys.readouterr().out


def test_outside_earnings_window_when_not_force_eligible():
    s = _build_strategy_tuned(
        force_eligible_threshold=0.90,
        strong_signal_threshold=0.70,
        max_earnings_days=5.0,
    )
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.75,
        earnings_proximity_days=30.0,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason == "outside_earnings_window"


def test_force_eligible_bypasses_outside_earnings_window():
    s = _build_strategy_tuned(max_earnings_days=5.0, min_trade_usdc=4.0)
    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.84,
        earnings_proximity_days=90.0,
        current_price_usd=2.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert plan is None
    assert reason == "small_trade_bypass"


def test_gas_above_limit_when_not_force_eligible():
    s = _build_strategy_tuned(
        gas_ok=False,
        force_eligible_threshold=0.92,
        strong_signal_threshold=0.70,
    )
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.78,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        allow_high_gas_override=False,
    )
    assert reason == "gas_above_limit"


def test_force_eligible_bypasses_high_gas_without_override():
    s = _build_strategy_tuned(gas_ok=False, min_trade_usdc=4.0)
    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        allow_high_gas_override=False,
    )
    assert plan is None
    assert reason == "small_trade_bypass"


def test_per_asset_cooldown_when_not_force_eligible():
    s = _build_strategy_tuned(force_eligible_threshold=0.92, strong_signal_threshold=0.70)

    def _never(sym: str, now: float | None, cd: int) -> bool:
        return False

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.78,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=_never,
    )
    assert reason == "per_asset_cooldown"


def test_x_signal_high_conviction_cooldown_bypass_before_full_cooldown(capsys):
    """TEMPORARY: BUY abs(signal)>=0.85 may pass at halved per-asset cooldown before full window expires."""
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_force_eligible_threshold(0.95)
        .with_strong_signal_threshold(0.70)
        .with_min_trade_usdc(4.0)
        .with_per_asset_cooldown_seconds(1800)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    reduced_cd = s._high_conviction_cooldown_seconds(0.88)
    assert reduced_cd == 900

    def _only_reduced_cooldown_ready(sym: str, now: float | None, cd: int) -> bool:
        return int(cd) == reduced_cd

    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.88,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=_only_reduced_cooldown_ready,
        upside_pct=25.0,
    )
    assert plan is not None
    assert reason is None
    assert plan.direction == "USDC_TO_EQUITY"
    assert "X-SIGNAL high-conviction cooldown bypass" in capsys.readouterr().out


def test_x_signal_high_conviction_cooldown_still_blocks_when_reduced_not_ready():
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_force_eligible_threshold(0.95)
        .with_strong_signal_threshold(0.70)
        .with_min_trade_usdc(4.0)
        .with_per_asset_cooldown_seconds(1800)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.88,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: False,
    )
    assert reason == "per_asset_cooldown"


def test_x_signal_very_strong_cooldown_more_aggressive_than_high_conviction():
    """TEMPORARY: BUY abs(signal)>=0.90 uses ~35% of base cooldown with 180s floor."""
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_per_asset_cooldown_seconds(1800)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    assert s._high_conviction_cooldown_seconds(0.88) == 900
    assert s._high_conviction_cooldown_seconds(0.92) == 630


def test_x_signal_very_strong_cooldown_bypass_before_full_cooldown(capsys):
    """TEMPORARY: BUY abs(signal)>=0.90 may pass at reduced cooldown before full window expires."""
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_force_eligible_threshold(0.95)
        .with_strong_signal_threshold(0.70)
        .with_min_trade_usdc(4.0)
        .with_per_asset_cooldown_seconds(1800)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    reduced_cd = s._high_conviction_cooldown_seconds(0.92)
    assert reduced_cd == 630

    def _only_reduced_cooldown_ready(sym: str, now: float | None, cd: int) -> bool:
        return int(cd) == reduced_cd

    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=_only_reduced_cooldown_ready,
        upside_pct=25.0,
    )
    assert plan is not None
    assert reason is None
    assert plan.direction == "USDC_TO_EQUITY"
    assert "X-SIGNAL very strong signal cooldown relief" in capsys.readouterr().out


def test_x_signal_very_strong_boosts_usdc_to_equity_trade_size(monkeypatch, capsys):
    """TEMPORARY: abs(signal)>=0.90 lifts dynamic BUY size toward ~$9.25 when band would be lower."""
    from modules import runtime as rt

    monkeypatch.setattr(rt, "FIXED_TRADE_USD_MIN", 8.0, raising=False)
    monkeypatch.setattr(rt, "FIXED_TRADE_USD_MAX", 8.0, raising=False)
    s = _build_strategy_tuned(strong_signal_threshold=0.90)
    size = s._compute_trade_size(100.0, 0.90)
    assert size == pytest.approx(strategy_module._X_SIGNAL_VERY_STRONG_SIZE_TARGET)
    assert "X-SIGNAL boosted sizing for very strong signal" in capsys.readouterr().out


def test_force_eligible_bypasses_cooldown_and_builds_buy():
    s = _build_strategy_tuned(min_trade_usdc=4.0)

    def _never(sym: str, now: float | None, cd: int) -> bool:
        return False

    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=_never,
    )
    assert plan is None
    assert reason == "small_trade_bypass"


def test_buy_blocked_zero_usdc():
    s = _build_strategy_tuned()
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=0.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason == "zero_usdc"


def test_buy_blocked_zero_usdc_logs_balance_source(capsys):
    s = _build_strategy_tuned()
    s.last_usdc_balance_source = "fallback_after_all_rpcs_failed"
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=0.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    out = capsys.readouterr().out
    assert reason == "zero_usdc"
    assert "source=" in out


def test_buy_fixed_size_is_now_stopped_by_hard_bypass_when_under_15():
    """BUY fixed sizing now enforces hard 15 USD floor even if legacy min_trade_usdc allows the amount."""
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert plan is None
    assert reason == "small_trade_bypass"


def test_buy_no_longer_uses_legacy_high_conviction_cap():
    """Regression: old per-asset cap removed; hard bypass remains the active small-trade guard."""
    s = _build_strategy_tuned(min_trade_usdc=5.0)
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=8,
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason == "small_trade_bypass"


def test_buy_wmatic_high_conviction_cap_is_blocked_when_min_trade_usd_is_22():
    """Regression: WMATIC high-conviction cap (~$4.50) must not bypass the configured minimum."""
    s = _build_strategy_tuned(min_trade_usdc=22.0)
    _, reason = s.build_plan_with_block_reason(
        symbol="WMATIC_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason == "below_min_trade_usdc"


def test_hard_bypass_blocks_micro_trade_under_15_usd():
    s = _build_strategy_tuned(min_trade_usdc=4.0)
    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert plan is None
    assert reason == "small_trade_bypass"


def test_x_signal_equity_high_conviction_allows_buy_below_hard_min_trade_usd(monkeypatch, capsys):
    """TEMPORARY: abs(signal)>=0.85 and size in [_X_SIGNAL_MIN_SIZE_OVERRIDE, hard_min) skips small_trade_bypass."""
    s = _build_strategy_tuned(min_trade_usdc=4.0)
    monkeypatch.setattr(
        SignalEquityTrader,
        "_compute_trade_size",
        lambda self, usdc_balance, signal_strength, usdt_balance=0.0, *, symbol="": 8.5,
    )
    plan, reason = s.build_plan_with_block_reason(
        symbol="WMATIC_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.90,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=25.0,
    )
    assert plan is not None
    assert plan.direction == "USDC_TO_EQUITY"
    assert reason is None
    assert "X-SIGNAL small size allowed (high conviction bypass)" in capsys.readouterr().out


def test_x_signal_equity_small_trade_still_blocked_below_override_floor(monkeypatch):
    s = _build_strategy_tuned(min_trade_usdc=4.0)
    monkeypatch.setattr(
        SignalEquityTrader,
        "_compute_trade_size",
        lambda self, usdc_balance, signal_strength, usdt_balance=0.0, *, symbol="": 7.4,
    )
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=25.0,
    )
    assert reason == "small_trade_bypass"


def test_query_onchain_usdc_balance_falls_back_to_snapshot_when_wallet_missing(monkeypatch):
    s = _build_strategy_tuned()
    monkeypatch.delenv("WALLET", raising=False)
    fallback = 33.25
    assert s._query_onchain_usdc_balance(fallback) == pytest.approx(fallback)
    assert s.last_usdc_balance_source == "fallback_missing_wallet_or_token"


def test_usdc_token_addresses_for_balance_includes_native_when_distinct(monkeypatch):
    s = _build_strategy_tuned()
    _pin_usdc_env(monkeypatch, bridged=USDC_E_TEST, native=USDC_NATIVE_TEST)
    assert s._usdc_token_addresses_for_balance() == [USDC_E_TEST, USDC_NATIVE_TEST]


def test_usdc_token_addresses_for_balance_skips_duplicate_native(monkeypatch):
    s = _build_strategy_tuned()
    _pin_usdc_env(monkeypatch, bridged=USDC_E_TEST, native=USDC_E_TEST)
    assert s._usdc_token_addresses_for_balance() == [USDC_E_TEST]


def test_query_onchain_usdc_balance_sums_native_and_bridged(monkeypatch):
    import nanoclaw.config as nc_cfg

    s = _build_strategy_tuned()
    _pin_usdc_env(monkeypatch, bridged=USDC_E_TEST, native=USDC_NATIVE_TEST)
    monkeypatch.setenv("RPC_ENDPOINTS", "https://rpc-one")
    monkeypatch.setenv("X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(s, "_rpc_endpoints_for_usdc_query", lambda: ["https://rpc-one"])

    balances = {
        USDC_E_TEST.lower(): 10_000_000,
        USDC_NATIVE_TEST.lower(): 47_000_000,
    }

    class _FakeContract:
        def __init__(self, token_address: str) -> None:
            self._token_address = str(token_address).lower()

        @property
        def functions(self):
            return self

        def balanceOf(self, _wallet):
            return self

        def call(self):
            return balances[self._token_address]

    class _FakeEth:
        def contract(self, address, abi):
            _ = abi
            return _FakeContract(str(address))

    class _FakeWeb3Client:
        eth = _FakeEth()

    monkeypatch.setattr(nc_cfg, "connect_web3", lambda *args, **kwargs: _FakeWeb3Client())

    out = s._query_onchain_usdc_balance(0.0)
    assert out == pytest.approx(57.0)
    assert s.last_usdc_balance_source == "onchain"


def test_query_onchain_usdc_balance_retries_and_succeeds(monkeypatch):
    import nanoclaw.config as nc_cfg

    s = _build_strategy_tuned()
    _pin_usdc_env(monkeypatch)
    monkeypatch.setenv("RPC_ENDPOINTS", "https://rpc-one")
    monkeypatch.setenv("X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(s, "_rpc_endpoints_for_usdc_query", lambda: ["https://rpc-one"])

    calls = {"count": 0}

    class _FakeContract:
        @property
        def functions(self):
            return self

        def balanceOf(self, _wallet):
            return self

        def call(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("temporary RPC error")
            return 102_870_000

    class _FakeEth:
        def contract(self, address, abi):
            _ = (address, abi)
            return _FakeContract()

    class _FakeWeb3Client:
        eth = _FakeEth()

    monkeypatch.setattr(nc_cfg, "connect_web3", lambda *args, **kwargs: _FakeWeb3Client())

    out = s._query_onchain_usdc_balance(10.0)
    assert out == pytest.approx(102.87)
    assert calls["count"] == 2
    assert s.last_usdc_balance_source == "onchain"


def test_query_onchain_usdc_balance_uses_fallback_only_after_retries(monkeypatch):
    import nanoclaw.config as nc_cfg

    s = _build_strategy_tuned()
    _pin_usdc_env(monkeypatch)
    monkeypatch.setenv("RPC_ENDPOINTS", "https://rpc-one")
    monkeypatch.setenv("X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(s, "_rpc_endpoints_for_usdc_query", lambda: ["https://rpc-one"])

    calls = {"count": 0}

    class _FakeContract:
        @property
        def functions(self):
            return self

        def balanceOf(self, _wallet):
            return self

        def call(self):
            calls["count"] += 1
            raise RuntimeError("RPC down")

    class _FakeEth:
        def contract(self, address, abi):
            _ = (address, abi)
            return _FakeContract()

    class _FakeWeb3Client:
        eth = _FakeEth()

    monkeypatch.setattr(nc_cfg, "connect_web3", lambda *args, **kwargs: _FakeWeb3Client())

    fallback = 41.5
    out = s._query_onchain_usdc_balance(fallback)
    assert out == pytest.approx(fallback)
    assert calls["count"] == 2
    assert s.last_usdc_balance_source == "fallback_after_all_rpcs_failed"


def test_query_onchain_usdc_balance_tries_next_rpc_when_previous_fails(monkeypatch):
    import nanoclaw.config as nc_cfg

    s = _build_strategy_tuned()
    _pin_usdc_env(monkeypatch)
    monkeypatch.setenv("RPC_ENDPOINTS", "https://rpc-one,https://rpc-two")
    monkeypatch.setenv("X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(s, "_rpc_endpoints_for_usdc_query", lambda: ["https://rpc-one", "https://rpc-two"])

    endpoints_seen: list[str] = []
    per_endpoint_calls = {"https://rpc-one": 0, "https://rpc-two": 0}

    class _FakeContract:
        def __init__(self, endpoint: str) -> None:
            self._endpoint = endpoint

        @property
        def functions(self):
            return self

        def balanceOf(self, _wallet):
            return self

        def call(self):
            per_endpoint_calls[self._endpoint] += 1
            if self._endpoint == "https://rpc-one":
                raise RuntimeError("rpc-one down")
            return 42_500_000

    class _FakeEth:
        def __init__(self, endpoint: str) -> None:
            self._endpoint = endpoint

        def contract(self, address, abi):
            _ = (address, abi)
            return _FakeContract(self._endpoint)

    class _FakeWeb3Client:
        def __init__(self, endpoint: str) -> None:
            self.eth = _FakeEth(endpoint)

    def _connect_web3(*, urls=None, **kwargs):
        _ = kwargs
        endpoint = str((urls or [None])[0])
        endpoints_seen.append(endpoint)
        return _FakeWeb3Client(endpoint)

    monkeypatch.setattr(nc_cfg, "connect_web3", _connect_web3)

    out = s._query_onchain_usdc_balance(10.0)
    assert out == pytest.approx(42.5)
    assert endpoints_seen == [
        "https://rpc-one",
        "https://rpc-one",
        "https://rpc-two",
    ]
    assert per_endpoint_calls["https://rpc-one"] == 2
    assert per_endpoint_calls["https://rpc-two"] == 1
    assert s.last_usdc_balance_source == "onchain"


def test_query_onchain_usdc_balance_uses_last_known_good_when_all_rpcs_fail(monkeypatch):
    import nanoclaw.config as nc_cfg

    s = _build_strategy_tuned()
    _pin_usdc_env(monkeypatch)
    monkeypatch.setenv("RPC_ENDPOINTS", "https://rpc-one,https://rpc-two")
    monkeypatch.setenv("X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(s, "_rpc_endpoints_for_usdc_query", lambda: ["https://rpc-one", "https://rpc-two"])

    class _AlwaysFailContract:
        @property
        def functions(self):
            return self

        def balanceOf(self, _wallet):
            return self

        def call(self):
            raise RuntimeError("RPC down")

    class _AlwaysFailEth:
        def contract(self, address, abi):
            _ = (address, abi)
            return _AlwaysFailContract()

    class _AlwaysFailWeb3Client:
        eth = _AlwaysFailEth()

    monkeypatch.setattr(nc_cfg, "connect_web3", lambda *args, **kwargs: _AlwaysFailWeb3Client())

    s._last_known_good_usdc_balance = 77.25
    out = s._query_onchain_usdc_balance(10.0)
    assert out == pytest.approx(77.25)
    assert s.last_usdc_balance_source == "fallback_last_known_good"


def test_buy_uses_onchain_balance_override_for_execution(monkeypatch):
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    monkeypatch.setattr(s, "_query_onchain_usdc_balance", lambda _fallback: 40.0)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 8.0)

    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=0.0,  # stale snapshot; should be replaced by on-chain read
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=20.0,
    )
    assert reason is None
    assert plan is not None
    assert plan.trade_size > 0.0


def test_buy_blocks_when_expected_profit_is_below_gas(monkeypatch):
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 1.0)
    monkeypatch.setattr(s, "_estimate_gas_cost_usd", lambda _gas_gwei: 2.0)

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=1.0,
    )
    assert reason == "expected_profit_below_gas"


def test_buy_blocks_when_effective_trade_after_gas_is_too_small(monkeypatch):
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 1.0)
    monkeypatch.setattr(s, "_estimate_gas_cost_usd", lambda _gas_gwei: 8.2)

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=400.0,
    )
    assert reason == "low_effective_trade_after_gas"


def test_x_signal_high_conviction_bypasses_low_effective_after_gas(monkeypatch, capsys):
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 1.0)
    monkeypatch.setattr(
        SignalEquityTrader,
        "_compute_trade_size",
        lambda self, usdc_balance, signal_strength, usdt_balance=0.0, *, symbol="": 15.0,
    )
    monkeypatch.setattr(s, "_estimate_gas_cost_usd", lambda _gas_gwei: 7.1)

    plan, reason = s.build_plan_with_block_reason(
        symbol="WMATIC_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.90,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=400.0,
    )
    assert plan is not None
    assert reason is None
    assert "X-SIGNAL effective size allowed (high conviction bypass)" in capsys.readouterr().out


def test_low_effective_after_gas_still_blocks_when_effective_below_override(monkeypatch):
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 1.0)
    monkeypatch.setattr(
        SignalEquityTrader,
        "_compute_trade_size",
        lambda self, usdc_balance, signal_strength, usdt_balance=0.0, *, symbol="": 15.0,
    )
    monkeypatch.setattr(s, "_estimate_gas_cost_usd", lambda _gas_gwei: 8.5)

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=400.0,
    )
    assert reason == "low_effective_trade_after_gas"


def test_low_effective_after_gas_not_bypassed_when_signal_below_085(monkeypatch):
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 1.0)
    monkeypatch.setattr(
        SignalEquityTrader,
        "_compute_trade_size",
        lambda self, usdc_balance, signal_strength, usdt_balance=0.0, *, symbol="": 15.0,
    )
    monkeypatch.setattr(s, "_estimate_gas_cost_usd", lambda _gas_gwei: 7.1)

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.84,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=40.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=400.0,
    )
    assert reason == "low_effective_trade_after_gas"


def test_limited_usdc_raises_force_eligible_threshold_to_085(monkeypatch):
    s = _build_strategy_tuned(force_eligible_threshold=0.80, strong_signal_threshold=0.90)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 50.0)
    monkeypatch.setattr(s, "_query_onchain_usdc_balance", lambda _fallback: 10.0)

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.82,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=10.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason is not None and "below_strong_threshold" in reason


def test_force_eligibility_uses_fresh_onchain_usdc_not_stale_param(monkeypatch):
    s = _build_strategy_tuned(force_eligible_threshold=0.80, strong_signal_threshold=0.90)
    monkeypatch.setattr(strategy_module, "_HARD_BYPASS_MIN_TRADE_USD", 50.0)
    # Stale upstream balance says "not limited", but fresh on-chain says USDC is limited.
    monkeypatch.setattr(s, "_query_onchain_usdc_balance", lambda _fallback: 10.0)

    _, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.82,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=100.0,  # stale snapshot (should not drive force-eligible gate)
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason is not None and "below_strong_threshold" in reason


def test_sell_path_equity_to_usdc():
    s = _build_strategy_tuned()
    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=-0.85,
        earnings_proximity_days=None,
        current_price_usd=2000.0,
        usdc_balance=50.0,
        equity_balance=2.5,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason is None
    assert plan is not None
    assert plan.direction == "EQUITY_TO_USDC"
    assert plan.amount_in > 0


def test_sell_blocked_zero_equity():
    s = _build_strategy_tuned()
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=-0.85,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason == "zero_equity_balance"


def test_load_followed_equities_empty_when_missing_file(tmp_path):
    missing = tmp_path / "nope.json"
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_followed_equities_path(str(missing))
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    assert s.load_followed_equities() == []


def test_load_followed_equities_empty_on_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_followed_equities_path(str(p))
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    assert s.load_followed_equities() == []


def test_load_followed_equities_skips_bad_rows(tmp_path):
    p = tmp_path / "fe.json"
    p.write_text(
        json.dumps(
            {
                "assets": [
                    "not-a-dict",
                    {"symbol": "BADLEN", "address": "0xshort"},
                    {"symbol": "OK", "address": "0x5555555555555555555555555555555555555555", "signal_strength": 0.5},
                ]
            }
        ),
        encoding="utf-8",
    )
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_followed_equities_path(str(p))
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    out = s.load_followed_equities()
    assert len(out) == 1
    assert out[0].symbol == "OK"


def test_build_plan_with_block_reason_skips_wbtc_link_alpha_even_if_loaded_elsewhere():
    """Hard skip in plan builder so a stray caller cannot hit balance reads for WBTC/LINK."""
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    for sym in ("WBTC_ALPHA", "LINK_ALPHA"):
        _, reason = s.build_plan_with_block_reason(
            symbol=sym,
            token_address="0x" + "1" * 40,
            token_decimals=18,
            signal_strength=0.92,
            earnings_proximity_days=None,
            current_price_usd=1.0,
            usdc_balance=50.0,
            equity_balance=0.0,
            wallet_address_for_gas="0x" + "3" * 40,
            can_trade_asset=lambda *_a, **_k: True,
        )
        assert reason == "temporary_skip_balance_workaround"


def test_load_followed_equities_temporary_skip_wbtc_link_alpha(tmp_path):
    """WBTC_ALPHA / LINK_ALPHA are temporarily omitted from the followed-equities load list."""
    p = tmp_path / "fe.json"
    p.write_text(
        json.dumps(
            {
                "assets": [
                    {"symbol": "WBTC_ALPHA", "address": "0x" + "1" * 40, "decimals": 8, "signal_strength": 0.92},
                    {"symbol": "LINK_ALPHA", "address": "0x" + "2" * 40, "decimals": 18, "signal_strength": 0.91},
                    {"symbol": "WMATIC_ALPHA", "address": "0x" + "3" * 40, "decimals": 18, "signal_strength": 0.85},
                    {"symbol": "WETH_ALPHA", "address": "0x" + "4" * 40, "decimals": 18, "signal_strength": 0.88},
                ]
            }
        ),
        encoding="utf-8",
    )
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_followed_equities_path(str(p))
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "5" * 40)
        .build()
    )
    out = s.load_followed_equities()
    assert [a.symbol for a in out] == ["WMATIC_ALPHA", "WETH_ALPHA"]


def test_gas_override_branch_when_force_eligible_and_allow_high_gas_override(capfd):
    """Logs GAS OVERRIDE line when gas hot but sprint override is on."""
    s = _build_strategy_tuned(gas_ok=False)
    s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        allow_high_gas_override=True,
    )
    captured = capfd.readouterr()
    assert "GAS OVERRIDE" in captured.out


def test_compute_trade_size_and_addrs_equal_helpers():
    s = _build_strategy(gas_ok=True, pol_balance=1.0)
    assert s._compute_trade_size(100.0, 0.90) > 0
    assert s._addrs_equal_case_insensitive("0xAbC", "0xabc") is True


def test_build_plan_skips_asset_when_dynamic_sizing_raises(capfd, monkeypatch):
    s = _build_strategy_tuned(min_trade_usdc=4.0, max_trade_usdc=200.0)
    monkeypatch.setattr(s, "_compute_trade_size", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("BadFunctionCallOutput")))

    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=8,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        upside_pct=20.0,
    )

    captured = capfd.readouterr()
    assert plan is None
    assert reason == "balance_read_failed"
    assert "[nanoclaw-av] BALANCE READ FAILED (skipped asset) | WETH_ALPHA | BadFunctionCallOutput" in captured.out


def test_build_plan_and_from_params_catch_block_reason_exceptions(capfd, monkeypatch):
    """Orchestration entry points must not propagate per-asset RPC/Web3 failures."""
    from nanoclaw.strategies.signal_equity_trader import EquityBuildPlanParams, FollowedEquity

    s = _build_strategy_tuned()
    monkeypatch.setattr(
        s,
        "build_plan_with_block_reason",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("BadFunctionCallOutput")),
    )
    plan = s.build_plan(
        symbol="LINK_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.92,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    out1 = capfd.readouterr().out
    assert plan is None
    assert "[nanoclaw-av] BALANCE READ FAILED (skipped asset) | LINK_ALPHA | BadFunctionCallOutput" in out1

    fe = FollowedEquity(
        symbol="WETH_ALPHA",
        token_address="0x" + "a" * 40,
        decimals=18,
        signal_strength=0.91,
    )
    params = EquityBuildPlanParams.for_eligible_asset(
        fe,
        usdc_balance=50.0,
        usdt_balance=0.0,
        equity_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        allow_high_gas_override=False,
    )
    plan2, reason2 = s.build_plan_from_params(params)
    out2 = capfd.readouterr().out
    assert plan2 is None and reason2 == "balance_read_failed"
    assert "[nanoclaw-av] BALANCE READ FAILED (skipped asset) | WETH_ALPHA | BadFunctionCallOutput" in out2


def test_buy_trade_size_multiplier_applies_before_guards(monkeypatch):
    from modules import runtime as rt
    from nanoclaw.strategies import signal_equity_trader as strat_mod

    # Ensure the scaled size stays above strategy-after-gas guardrails.
    monkeypatch.setattr(rt, "FIXED_TRADE_USD_MIN", 20.0, raising=False)
    monkeypatch.setattr(rt, "FIXED_TRADE_USD_MAX", 20.0, raising=False)
    monkeypatch.setattr(strat_mod, "_HARD_BYPASS_MIN_TRADE_USD", 0.0, raising=False)

    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_min_trade_usdc(1.0)
        .with_max_trade_usdc(100.0)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )

    plan, reason = s.build_plan_with_block_reason(
        symbol="WETH_ALPHA",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=0.95,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=100.0,
        equity_balance=0.0,
        usdt_balance=0.0,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
        trade_size_multiplier=0.50,
        buy_risk_level="MEDIUM",
    )
    assert reason is None
    assert plan is not None
    assert plan.trade_size == pytest.approx(10.0)


def test_builder_fluent_setters_round_trip():
    """Exercise optional builder chain (trade sizing / POL / TP wiring)."""
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_trade_pct_of_usdc(0.19)
        .with_max_trade_usdc(27.0)
        .with_min_pol_for_gas(0.006)
        .with_strong_take_profit_pct(11.0)
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    assert s.config.trade_pct_of_usdc == pytest.approx(0.19)
    assert s.config.max_trade_usdc == pytest.approx(27.0)
    assert s.config.min_pol_for_gas == pytest.approx(0.006)
    assert s.config.strong_take_profit_pct == pytest.approx(11.0)


def test_sell_path_blocks_dust_amount():
    s = _build_strategy_tuned()
    # Positive token units round down to 0 at this precision (still >0 float balance).
    dust = 1e-22
    _, reason = s.build_plan_with_block_reason(
        symbol="WETH",
        token_address="0x" + "1" * 40,
        token_decimals=18,
        signal_strength=-0.88,
        earnings_proximity_days=None,
        current_price_usd=1.0,
        usdc_balance=50.0,
        equity_balance=dust,
        wallet_address_for_gas="0x" + "3" * 40,
        can_trade_asset=lambda *_a, **_k: True,
    )
    assert reason == "sell_amount_below_min_units"


def test_load_skips_asset_when_symbol_but_no_resolvable_address(tmp_path, monkeypatch):
    monkeypatch.delenv("SOLO", raising=False)
    p = tmp_path / "solo.json"
    p.write_text(
        json.dumps({"assets": [{"symbol": "SOLO"}]}),
        encoding="utf-8",
    )
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_followed_equities_path(str(p))
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    assert s.load_followed_equities() == []


def test_load_coerces_invalid_min_signal_string_and_out_of_range(tmp_path):
    p = tmp_path / "mm.json"
    p.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "symbol": "A",
                        "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        "min_signal_strength": "bad",
                    },
                    {
                        "symbol": "B",
                        "address": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        "min_signal_strength": 2.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    s = (
        SignalEquityTrader.builder()
        .with_enabled(True)
        .with_followed_equities_path(str(p))
        .with_gas_protector(DummyProtector(gas_ok=True, pol_balance=1.0))
        .with_usdc_address("0x" + "2" * 40)
        .build()
    )
    out = s.load_followed_equities()
    assert len(out) == 2
    assert out[0].min_signal_strength is None
    assert out[1].min_signal_strength is None
