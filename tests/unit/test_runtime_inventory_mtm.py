"""Inventory MTM for FE_USD: router quote then Uniswap V3 quoter fallback."""

from __future__ import annotations

import pytest

from modules import runtime


def test_quote_followed_token_usdt_mtm_uses_v3_when_router_fails(monkeypatch) -> None:
    def _router_fail(*_a, **_k):
        raise RuntimeError("no v2 path")

    def _v3_quote(_w3, **kwargs):
        if int(kwargs.get("fee", 0)) == 3000:
            return (2_500_000, 2_300_000)
        raise RuntimeError("no pool")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_fail)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        _v3_quote,
    )
    out = runtime._quote_followed_token_usdt_mtm(
        runtime.w3,
        token_in="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in_raw=1_000_000_000_000_000_000,
        slippage_bps=300,
    )
    assert out == pytest.approx(2.5)


def test_quote_followed_token_usdt_mtm_returns_zero_on_total_failure(monkeypatch) -> None:
    def _router_fail(*_a, **_k):
        raise RuntimeError("no v2 path")

    def _v3_fail(*_a, **_k):
        raise RuntimeError("no v3")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_fail)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        _v3_fail,
    )
    out = runtime._quote_followed_token_usdt_mtm(
        runtime.w3,
        token_in="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in_raw=1_000_000_000_000_000_000,
        slippage_bps=300,
    )
    assert out == pytest.approx(0.0)


def test_quote_followed_token_usdt_mtm_prefers_router_when_ok(monkeypatch) -> None:
    def _router_ok(_w3, **_k):
        return ([], 3_000_000, 2_900_000)

    def _v3_should_not_run(*_a, **_k):
        raise AssertionError("v3 should not run when router succeeds")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_ok)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        _v3_should_not_run,
    )
    out = runtime._quote_followed_token_usdt_mtm(
        runtime.w3,
        token_in="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in_raw=10**18,
        slippage_bps=300,
    )
    assert out == pytest.approx(3.0)
