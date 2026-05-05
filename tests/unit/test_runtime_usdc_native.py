"""_total_usdc_balance aggregates USDC.e and native USDC when both are configured."""

from __future__ import annotations

import pytest

USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_NAT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"


@pytest.fixture
def runtime_mod(monkeypatch: pytest.MonkeyPatch):
    import modules.runtime as r

    monkeypatch.setattr(r, "USDC", USDC_E)
    monkeypatch.setattr(r, "USDC_NATIVE", USDC_NAT)
    return r


def test_total_usdc_sums_native_when_distinct(runtime_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_balance(
        token_address: str,
        decimals: int = 6,
        web3_client=None,
        wallet_address: str = "",
    ) -> float:
        t = str(token_address).strip().lower()
        if t == USDC_E.lower():
            return 10.0
        if t == USDC_NAT.lower():
            return 25.765
        return -1.0

    monkeypatch.setattr(runtime_mod, "get_token_balance", fake_balance)
    assert runtime_mod._total_usdc_balance() == pytest.approx(35.765)


def test_total_usdc_native_skipped_when_same_as_usdc(runtime_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_mod, "USDC_NATIVE", USDC_E)

    def fake_balance(
        token_address: str,
        decimals: int = 6,
        web3_client=None,
        wallet_address: str = "",
    ) -> float:
        t = str(token_address).strip().lower()
        if t == USDC_E.lower():
            return 42.0
        return 99.0

    monkeypatch.setattr(runtime_mod, "get_token_balance", fake_balance)
    assert runtime_mod._total_usdc_balance() == pytest.approx(42.0)
