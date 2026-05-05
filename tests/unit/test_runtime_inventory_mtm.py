"""Inventory MTM for FE_USD: router quote then Uniswap V3 QuoterV2 / legacy quoter."""

from __future__ import annotations

import pytest

from modules import runtime


def test_quote_followed_token_usdt_mtm_uses_quoterv2_when_router_fails(monkeypatch) -> None:
    def _router_fail(*_a, **_k):
        raise RuntimeError("no v2 path")

    def _qv2(_w3, **kwargs):
        if int(kwargs.get("fee", 0)) == 3000:
            return 2_500_000
        raise RuntimeError("no pool")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_fail)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single_quoterv2",
        _qv2,
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("legacy quoter should not run")),
    )
    out = runtime._quote_followed_token_usdt_mtm(
        runtime.w3,
        token_in="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in_raw=1_000_000_000_000_000_000,
        slippage_bps=300,
    )
    assert out == pytest.approx(2.5)


def test_quote_followed_token_usdt_mtm_falls_back_to_legacy_quoter(monkeypatch) -> None:
    def _router_fail(*_a, **_k):
        raise RuntimeError("no v2 path")

    def _qv2_fail(*_a, **_k):
        raise RuntimeError("quoterv2 reverts")

    def _qv1(_w3, **kwargs):
        if int(kwargs.get("fee", 0)) == 3000:
            return (2_000_000, 1_900_000)
        raise RuntimeError("no pool")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_fail)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single_quoterv2",
        _qv2_fail,
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        _qv1,
    )
    out = runtime._quote_followed_token_usdt_mtm(
        runtime.w3,
        token_in="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in_raw=10**18,
        slippage_bps=300,
    )
    assert out == pytest.approx(2.0)


def test_quote_followed_token_usdt_mtm_returns_zero_on_total_failure(monkeypatch) -> None:
    def _router_fail(*_a, **_k):
        raise RuntimeError("no v2 path")

    def _qv2_fail(*_a, **_k):
        raise RuntimeError("no v3 v2")

    def _v1_fail(*_a, **_k):
        raise RuntimeError("no v3 v1")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_fail)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single_quoterv2",
        _qv2_fail,
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        _v1_fail,
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_multihop_quoterv2",
        _v1_fail,
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

    def _qv2_should_not_run(*_a, **_k):
        raise AssertionError("quoterv2 should not run when router succeeds")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_ok)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single_quoterv2",
        _qv2_should_not_run,
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        _qv2_should_not_run,
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_multihop_quoterv2",
        _qv2_should_not_run,
    )
    out = runtime._quote_followed_token_usdt_mtm(
        runtime.w3,
        token_in="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in_raw=10**18,
        slippage_bps=300,
    )
    assert out == pytest.approx(3.0)


def test_encode_uniswap_v3_path_two_hop() -> None:
    from web3 import Web3

    from nanoclaw.execution.uniswap_v3_helpers import encode_uniswap_v3_path

    w = Web3.to_checksum_address("0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619")
    u = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
    t = Web3.to_checksum_address("0xc2132D05D31c914a87C6611C10748AEb04B58e8F")
    p = encode_uniswap_v3_path([w, u, t], [500, 500])
    assert len(p) == 20 + 3 + 20 + 3 + 20


def test_quote_followed_token_usdt_mtm_uses_multihop_when_direct_fails(monkeypatch) -> None:
    def _router_fail(*_a, **_k):
        raise RuntimeError("no v2 path")

    monkeypatch.setattr("swap_executor._best_quote_path", _router_fail)
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single_quoterv2",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("direct")),
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_single",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("legacy")),
    )
    monkeypatch.setattr(
        "nanoclaw.execution.uniswap_v3_helpers.quote_exact_input_multihop_quoterv2",
        lambda *_a, **_k: 4_000_000,
    )
    out = runtime._quote_followed_token_usdt_mtm(
        runtime.w3,
        token_in="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        amount_in_raw=10**18,
        slippage_bps=300,
    )
    assert out == pytest.approx(4.0)
