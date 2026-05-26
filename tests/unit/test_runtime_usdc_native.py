"""_total_usdc_balance aggregates USDC.e and native USDC when both are configured."""

from __future__ import annotations

import pytest

USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_NAT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WMATIC = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"


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


# region stables drift regression (Cleanup #3, May 2026)
# These tests integrate at the ``get_balances()`` surface — not just the
# ``_total_usdc_balance()`` helper — to pin the contract that:
#   1. Both USDC variants flow through ``Balances.usdc`` exactly once (no
#      double-count, no skip).
#   2. ``Balances.usdt`` is read fresh from on-chain per call (no module-level
#      cache that could leak a pre-trade reservation into a post-trade total).
# Symptom 2026-05-26: bot USDC $31.53 vs wallet $41.76 (short $10.23) and bot
# USDT $29.27 vs wallet $10.48 (over $18.79), net stables +$8.56 over. Pure
# steady-state arithmetic should never produce that gap; an in-flight swap
# reservation can, which is acceptance-criterion-A defined as out-of-scope, so
# these tests pin only the steady-state invariants.


def test_get_balances_sums_both_usdc_variants_through_balances_usdc(
    runtime_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion D: both USDC variants reach ``Balances.usdc`` once.

    A bug that read only USDC.e (drops native), only USDC_NATIVE (drops
    bridged), or summed one variant twice would fail this assertion.
    """
    monkeypatch.setattr(runtime_mod, "USDT", USDT)
    monkeypatch.setattr(runtime_mod, "WMATIC", WMATIC)
    call_count: dict[str, int] = {}

    def fake_balance(
        token_address: str,
        decimals: int = 6,
        web3_client=None,
        wallet_address: str = "",
    ) -> float:
        t = str(token_address).strip().lower()
        call_count[t] = call_count.get(t, 0) + 1
        if t == USDC_E.lower():
            return 37.50
        if t == USDC_NAT.lower():
            return 4.26
        if t == USDT.lower():
            return 10.48
        if t == WMATIC.lower():
            return 0.0
        return -1.0

    monkeypatch.setattr(runtime_mod, "get_token_balance", fake_balance)
    monkeypatch.setattr(runtime_mod, "get_pol_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(runtime_mod, "_followed_equity_tokens_usdt_usd", lambda: 0.0)
    monkeypatch.setattr("protection.get_live_wmatic_price", lambda: 0.0)

    b = runtime_mod.get_balances()
    assert b.usdc == pytest.approx(37.50 + 4.26)
    assert b.usdt == pytest.approx(10.48)
    # Exactly one balanceOf call per ERC20 contract per cycle (no double-count).
    assert call_count.get(USDC_E.lower(), 0) == 1
    assert call_count.get(USDC_NAT.lower(), 0) == 1
    assert call_count.get(USDT.lower(), 0) == 1


def test_get_balances_does_not_count_usdc_twice_when_native_aliases_usdce(
    runtime_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bridged USDC_NATIVE = USDC config (operator typo) must not double-count.

    Defends against a future change that loosened the case-insensitive dedup
    in ``_total_usdc_balance``.
    """
    monkeypatch.setattr(runtime_mod, "USDC_NATIVE", USDC_E.upper())  # casing diff
    monkeypatch.setattr(runtime_mod, "USDT", USDT)
    monkeypatch.setattr(runtime_mod, "WMATIC", WMATIC)

    def fake_balance(token_address: str, *_a, **_k) -> float:
        t = str(token_address).strip().lower()
        if t == USDC_E.lower():
            return 25.0
        return 0.0

    monkeypatch.setattr(runtime_mod, "get_token_balance", fake_balance)
    monkeypatch.setattr(runtime_mod, "get_pol_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(runtime_mod, "_followed_equity_tokens_usdt_usd", lambda: 0.0)
    monkeypatch.setattr("protection.get_live_wmatic_price", lambda: 0.0)

    b = runtime_mod.get_balances()
    assert b.usdc == pytest.approx(25.0), "USDC variant must not be double-counted"


def test_get_balances_reads_usdt_fresh_each_call(
    runtime_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    """USDT must reflect the latest on-chain value, not a stale module-level cache.

    If ``get_balances`` cached the USDT read (e.g. via a global), a swap that
    debited USDT mid-cycle would appear in TOTAL at its pre-trade value — the
    2026-05-26 +$18.79 USDT overcount shape.
    """
    monkeypatch.setattr(runtime_mod, "USDC", USDC_E)
    monkeypatch.setattr(runtime_mod, "USDC_NATIVE", USDC_NAT)
    monkeypatch.setattr(runtime_mod, "USDT", USDT)
    monkeypatch.setattr(runtime_mod, "WMATIC", WMATIC)

    usdt_series = iter([29.27, 10.48])

    def fake_balance(token_address: str, *_a, **_k) -> float:
        t = str(token_address).strip().lower()
        if t == USDT.lower():
            return next(usdt_series)
        return 0.0

    monkeypatch.setattr(runtime_mod, "get_token_balance", fake_balance)
    monkeypatch.setattr(runtime_mod, "get_pol_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(runtime_mod, "_followed_equity_tokens_usdt_usd", lambda: 0.0)
    monkeypatch.setattr("protection.get_live_wmatic_price", lambda: 0.0)

    first = runtime_mod.get_balances()
    second = runtime_mod.get_balances()
    assert first.usdt == pytest.approx(29.27)
    assert second.usdt == pytest.approx(10.48), (
        "Second get_balances() must see the fresh on-chain USDT value, not the first call's cached read"
    )


# endregion
