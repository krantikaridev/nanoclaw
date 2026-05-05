from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from nanoclaw.utils.gas_protector import GasProtector
from modules import wallet_performance as wp
import config as cfg


class _DummyProtector(GasProtector):
    def __init__(self, *, gas_ok: bool = True, gas_gwei: float = 50.0) -> None:
        self._gas_ok = gas_ok
        self._gas_gwei = gas_gwei

    def get_safe_status(self, address: str, urgent: bool = False, min_pol: float | None = None) -> dict:  # type: ignore[override]
        _ = (address, urgent, min_pol)
        return {
            "ok": self._gas_ok,
            "gas_ok": self._gas_ok,
            "pol_balance": 1.0,
            "gas_gwei": self._gas_gwei,
            "max_gwei": 80.0,
            "min_pol_balance": float(min_pol or 0.0),
        }


def _build_strategy(*, gas_ok: bool = True, gas_gwei: float = 50.0) -> USDCopyStrategy:
    return (
        USDCopyStrategy.builder()
        .with_enabled(True)
        .with_copy_trade_pct(0.20)
        .with_min_trade_usdc(5.0)
        .with_max_trade_usdc(15.0)
        .with_gas_protector(_DummyProtector(gas_ok=gas_ok, gas_gwei=gas_gwei))
        .build()
    )


def test_usdc_copy_skips_when_expected_edge_below_gas_threshold(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_FILE", str(tmp_path / "wallet_perf.json"))
    monkeypatch.setattr(cfg, "COPY_BASE_EXPECTED_EDGE_PCT", 2.0)
    monkeypatch.setattr(cfg, "COPY_GAS_EDGE_MULTIPLIER", 2.5)
    monkeypatch.setattr(cfg, "COPY_MIN_EFFECTIVE_TRADE_AFTER_GAS_USD", 10.0)
    strategy = _build_strategy(gas_ok=True, gas_gwei=80.0)

    plan = strategy.build_plan(
        usdc_balance=20.0,
        usdt_balance=20.0,
        wallets=["0x1111111111111111111111111111111111111111"],
        wallet_address_for_gas="0x3333333333333333333333333333333333333333",
        can_trade_wallet=lambda *_a, **_k: True,
    )
    assert plan is None


def test_usdc_copy_deprioritizes_poor_wallet_and_uses_healthier_wallet(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_FILE", str(tmp_path / "wallet_perf.json"))
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_WINDOW_TRADES", 5)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_MIN_TRADES", 3)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_POOR_WINRATE", 0.5)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_POOR_AVG_PNL_USD", -0.1)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_PENALTY_MULTIPLIER", 0.6)
    monkeypatch.setattr(cfg, "COPY_BASE_EXPECTED_EDGE_PCT", 20.0)
    monkeypatch.setattr(cfg, "COPY_MIN_EFFECTIVE_TRADE_AFTER_GAS_USD", 8.0)

    poor = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    good = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    for _ in range(3):
        wp.record_copy_entry(poor, entry_price_usd=1.0, notional_usd=10.0)
        wp.record_copy_exit(exit_price_usd=0.9, exit_notional_usd=10.0)

    strategy = _build_strategy(gas_ok=True, gas_gwei=20.0)
    plan = strategy.build_plan(
        usdc_balance=50.0,
        usdt_balance=50.0,
        wallets=[poor, good],
        wallet_address_for_gas="0x3333333333333333333333333333333333333333",
        can_trade_wallet=lambda *_a, **_k: True,
    )
    assert plan is not None
    assert plan.wallet == good


def test_usdc_copy_skips_when_global_min_trade_exceeds_max_trade_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_FILE", str(tmp_path / "wallet_perf.json"))
    monkeypatch.setattr(cfg, "MIN_TRADE_USD", 20.0)
    strategy = _build_strategy(gas_ok=True, gas_gwei=20.0)

    plan = strategy.build_plan(
        usdc_balance=50.0,
        usdt_balance=50.0,
        wallets=["0x1111111111111111111111111111111111111111"],
        wallet_address_for_gas="0x3333333333333333333333333333333333333333",
        can_trade_wallet=lambda *_a, **_k: True,
    )
    assert plan is None
