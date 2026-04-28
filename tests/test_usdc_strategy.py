from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from nanoclaw.utils.gas_protector import GasProtector


class DummyProtector(GasProtector):
    def __init__(self, ok: bool = True) -> None:
        # Bypass parent init; we only need get_safe_status in these tests.
        self._ok = ok

    def get_safe_status(self, address: str, urgent: bool = False, min_pol: float | None = None) -> dict:  # type: ignore[override]
        return {"ok": self._ok}


def test_builder_requires_gas_protector():
    builder = USDCopyStrategy.builder().with_enabled(True)
    try:
        builder.build()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "GasProtector" in str(exc)


def test_disabled_strategy_returns_no_plan():
    strat = USDCopyStrategy.builder().with_enabled(False).with_gas_protector(DummyProtector(ok=True)).build()

    plan = strat.build_plan(
        usdc_balance=100.0,
        wallets=["0xabc"],
        wallet_address_for_gas="0xwallet",
        can_trade_wallet=lambda w, now, cooldown: True,
        mark_wallet_traded=lambda w, now, cooldown: None,
        now=1000.0,
    )

    assert plan is None


def test_enabled_strategy_builds_plan_and_marks_wallet():
    marked = {"count": 0, "wallet": None}

    def mark(wallet, now, cooldown):
        marked["count"] += 1
        marked["wallet"] = wallet

    strat = (
        USDCopyStrategy.builder()
        .with_enabled(True)
        .with_copy_trade_pct(0.10)
        .with_min_trade_usdc(5.0)
        .with_max_trade_usdc(15.0)
        .with_per_wallet_cooldown_seconds(300)
        .with_min_pol_for_gas(0.05)
        .with_gas_protector(DummyProtector(ok=True))
        .build()
    )

    plan = strat.build_plan(
        usdc_balance=120.0,
        wallets=["0xaaa", "0xbbb"],
        wallet_address_for_gas="0xwallet",
        can_trade_wallet=lambda w, now, cooldown: w == "0xbbb",
        mark_wallet_traded=mark,
        now=1000.0,
    )

    assert plan is not None
    assert plan.trade_size == 12.0
    assert plan.amount_in == 12_000_000
    assert "USDC COPY" in plan.message
    assert marked["count"] == 1
    assert marked["wallet"] == "0xbbb"


def test_gas_protection_blocks_plan():
    strat = USDCopyStrategy.builder().with_enabled(True).with_gas_protector(DummyProtector(ok=False)).build()

    plan = strat.build_plan(
        usdc_balance=100.0,
        wallets=["0xabc"],
        wallet_address_for_gas="0xwallet",
        can_trade_wallet=lambda w, now, cooldown: True,
        mark_wallet_traded=lambda w, now, cooldown: None,
        now=1000.0,
    )

    assert plan is None

