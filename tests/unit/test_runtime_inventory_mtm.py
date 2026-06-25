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


# region FE_USD fallback / visibility regression
# These tests cover the May 2026 incident where LINK_ALPHA holdings were silently
# excluded from TOTAL because all on-chain quote tiers returned 0 AND
# `current_price_usd` was unset in `followed_equities.json`. The result was a
# multi-dollar undercount in the operator-facing PnL with zero diagnostic signal.

class _FakeAsset:
    def __init__(self, symbol: str, addr: str, decimals: int, current_price_usd: float | None) -> None:
        self.symbol = symbol
        self.token_address = addr
        self.decimals = decimals
        self.current_price_usd = current_price_usd


def test_followed_equity_uses_current_price_fallback_when_quote_zero(monkeypatch, capsys, tmp_path) -> None:
    """When live quote returns 0 but `current_price_usd` is set, fe_usd must use bal*price."""
    monkeypatch.setattr(
        runtime,
        "FE_USD_SPOT_CACHE_FILE",
        str(tmp_path / "fe_usd_spot_cache.json"),
    )
    asset = _FakeAsset(
        symbol="LINK_ALPHA",
        addr="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03FaBad39",
        decimals=18,
        current_price_usd=9.43,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 8.676)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: 0.0,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(8.676 * 9.43, rel=1e-6)
    captured = capsys.readouterr().out
    assert "FE_USD UNQUOTED" in captured
    assert "LINK_ALPHA" in captured
    assert "fallback_px_usd=9.4300" in captured


def test_followed_equity_zero_quote_zero_fallback_still_visible(monkeypatch, capsys, tmp_path) -> None:
    """Even when no fallback price is set, the operator must see the unquoted line."""
    monkeypatch.setattr(
        runtime,
        "FE_USD_SPOT_CACHE_FILE",
        str(tmp_path / "fe_usd_spot_cache.json"),
    )
    asset = _FakeAsset(
        symbol="WBTC_ALPHA",
        addr="0xdead000000000000000000000000000000000001",
        decimals=8,
        current_price_usd=None,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 0.00012)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: 0.0,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(0.0)
    captured = capsys.readouterr().out
    assert "FE_USD UNQUOTED" in captured
    assert "WBTC_ALPHA" in captured
    assert "contributed_to_total=$0.00" in captured


def test_followed_equity_uses_max_of_live_and_fallback(monkeypatch, capsys, tmp_path) -> None:
    """Cleanup #3 (May 2026): effective FE_USD per asset = max(live_quote, bal*fallback).

    Pre-cleanup, live quote always won when > 0. That allowed a degraded on-chain
    quote (drained pool, large-size price impact) to silently undercount TOTAL —
    the May 2026 LINK_ALPHA incident where 5.676 LINK MTM'd at ~$35.78 while
    spot * bal was ~$53.52. Now ``current_price_usd`` in followed_equities.json
    is a true fallback FLOOR: the larger of (live, fallback × bal) wins.
    Prior-cycle last-good spot cache anchors the floor when live is degraded.
    """
    cache_path = tmp_path / "fe_usd_spot_cache.json"
    cache_path.write_text(
        '{"LINK_ALPHA": {"spot_usd": 9.43, "updated_unix": 1700000000.0}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="LINK_ALPHA",
        addr="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03FaBad39",
        decimals=18,
        current_price_usd=9.43,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 5.676)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: 35.78,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    # bal * fallback ≈ 53.52 > live 35.78 → fallback floor wins.
    assert fe_usd == pytest.approx(5.676 * 9.43, rel=1e-6)
    captured = capsys.readouterr().out
    assert "FE_USD FALLBACK FLOOR APPLIED" in captured
    assert "LINK_ALPHA" in captured
    assert "live_quote_usdt=$35.78" in captured
    import json

    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert float(saved["LINK_ALPHA"]["spot_usd"]) == pytest.approx(9.43, rel=1e-6)


def test_fe_usd_degraded_live_does_not_poison_spot_cache(monkeypatch, tmp_path) -> None:
    """P1 + Cleanup #3: fallback-winning degraded live must not overwrite prior last-good spot."""
    import json

    cache_path = tmp_path / "fe_usd_spot_cache.json"
    cache_path.write_text(
        '{"LINK_ALPHA": {"spot_usd": 9.43, "updated_unix": 1700000000.0}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="LINK_ALPHA",
        addr="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03FaBad39",
        decimals=18,
        current_price_usd=9.43,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 5.676)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: 35.78,
    )
    runtime._followed_equity_tokens_usdt_usd()
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert float(saved["LINK_ALPHA"]["spot_usd"]) == pytest.approx(9.43, rel=1e-6)
    assert float(saved["LINK_ALPHA"]["updated_unix"]) == pytest.approx(1700000000.0, rel=1e-6)


def test_followed_equity_live_quote_wins_when_above_fallback(monkeypatch, capsys, tmp_path) -> None:
    """When live quote ≥ bal*fallback, live wins (no floor logging, no fallback bump)."""
    monkeypatch.setattr(
        runtime,
        "FE_USD_SPOT_CACHE_FILE",
        str(tmp_path / "fe_usd_spot_cache.json"),
    )
    asset = _FakeAsset(
        symbol="LINK_ALPHA",
        addr="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03FaBad39",
        decimals=18,
        current_price_usd=9.43,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 1.0)
    # live $12.00 > fallback 1 × $9.43 = $9.43 → live wins.
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: 12.0,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(12.0)
    captured = capsys.readouterr().out
    assert "FE_USD UNQUOTED" not in captured
    assert "FALLBACK FLOOR APPLIED" not in captured


def test_followed_equity_fe_usd_equals_bal_times_max_of_quote_per_unit_and_fallback(
    monkeypatch, tmp_path
) -> None:
    """Acceptance criterion C: FE_USD = bal × max(live_quote_per_unit, fallback_per_unit).

    Pins the contract that the task spec calls out explicitly. The function returns
    USDT-notional, which is ``bal × effective_unit_price``, where
    ``effective_unit_price = max(live_quote_total / bal, fallback_usd)``.
    Prior last-good spot cache supplies the fallback per-unit floor.
    """
    bal = 4.0
    fallback = 5.0
    live_total = 12.0  # equivalent to $3.00 / unit, below the $5 fallback
    expected = bal * max(live_total / bal, fallback)  # = max(12, 20) = 20.0

    cache_path = tmp_path / "fe_usd_spot_cache.json"
    cache_path.write_text(
        f'{{"LINK_ALPHA": {{"spot_usd": {fallback}, "updated_unix": 1700000000.0}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="LINK_ALPHA",
        addr="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03FaBad39",
        decimals=18,
        current_price_usd=fallback,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: bal)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: live_total,
    )
    assert runtime._followed_equity_tokens_usdt_usd() == pytest.approx(expected)


def test_followed_equities_json_has_fallback_prices_for_held_assets() -> None:
    """Regression: ensure operator-facing fallback prices are populated post-incident."""
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    data = json.loads((repo_root / "followed_equities.json").read_text(encoding="utf-8"))
    by_sym = {a["symbol"]: a for a in data["assets"]}
    for sym in ("WETH_ALPHA", "WBTC_ALPHA", "LINK_ALPHA", "AAVE_ALPHA", "UNI_ALPHA"):
        assert "current_price_usd" in by_sym[sym], f"missing fallback price for {sym}"
        assert float(by_sym[sym]["current_price_usd"]) > 0


def test_fe_usd_stale_json_floor_live_wins_with_spot_cache(monkeypatch, capsys, tmp_path) -> None:
    """P1: stale JSON floor 2500 + healthy live ~$2000/token → live wins, not inflated fallback."""
    bal = 0.039756
    live = 79.53
    cache_path = tmp_path / "fe_usd_spot_cache.json"
    cache_path.write_text(
        '{"WETH_ALPHA": {"spot_usd": 2000.0, "updated_unix": 1700000000.0}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="WETH_ALPHA",
        addr="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        current_price_usd=2500.0,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: bal)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: live,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(live, abs=0.02)
    captured = capsys.readouterr().out
    assert "FE_USD FALLBACK FLOOR APPLIED" not in captured


def test_fe_usd_slight_cache_drift_refreshes_to_live(monkeypatch, capsys, tmp_path) -> None:
    """Agent H: stage VM — cache 2022 vs live ~1995/token → refresh, live wins, no fallback log."""
    bal = 0.065007
    live = 129.70
    cached_spot = 2022.7890
    cache_path = tmp_path / "fe_usd_spot_cache.json"
    cache_path.write_text(
        f'{{"WETH_ALPHA": {{"spot_usd": {cached_spot}, "updated_unix": 1700000000.0}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    monkeypatch.setattr(runtime.cfg, "FE_USD_FALLBACK_REFRESH_ENABLED", True, raising=False)
    monkeypatch.setattr(runtime.cfg, "FE_USD_FALLBACK_MAX_STALE_PCT", 5.0, raising=False)
    asset = _FakeAsset(
        symbol="WETH_ALPHA",
        addr="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        current_price_usd=2500.0,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: bal)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: live,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(live, abs=0.05)
    captured = capsys.readouterr().out
    assert "FE_USD FALLBACK REFRESH" in captured
    assert "FE_USD FALLBACK FLOOR APPLIED" not in captured


def test_fe_usd_live_zero_uses_last_good_spot_cache(monkeypatch, tmp_path) -> None:
    """P1: live=0 → MTM from prior last-good spot, not stale JSON alone."""
    bal = 0.04
    cached_spot = 2000.0
    cache_path = tmp_path / "fe_usd_spot_cache.json"
    cache_path.write_text(
        f'{{"WETH_ALPHA": {{"spot_usd": {cached_spot}, "updated_unix": 1700000000.0}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="WETH_ALPHA",
        addr="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        current_price_usd=2500.0,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: bal)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: 0.0,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(bal * cached_spot, rel=1e-6)


def test_fe_usd_first_run_no_cache_uses_json_when_live_zero(monkeypatch, tmp_path) -> None:
    """P1: no cache and live=0 → JSON seed floor only."""
    bal = 8.676
    json_floor = 9.43
    cache_path = tmp_path / "fe_usd_spot_cache.json"
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="LINK_ALPHA",
        addr="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03FaBad39",
        decimals=18,
        current_price_usd=json_floor,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: bal)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: 0.0,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(bal * json_floor, rel=1e-6)
    assert not cache_path.exists()


def test_fe_usd_first_run_no_cache_anchors_floor_to_live(monkeypatch, capsys, tmp_path) -> None:
    """P1: first run with healthy live quote caps stale JSON floor same cycle."""
    bal = 0.039756
    live = 79.53
    cache_path = tmp_path / "fe_usd_spot_cache.json"
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="WETH_ALPHA",
        addr="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        current_price_usd=2500.0,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: bal)
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: live,
    )
    fe_usd = runtime._followed_equity_tokens_usdt_usd()
    assert fe_usd == pytest.approx(live, abs=0.02)
    captured = capsys.readouterr().out
    assert "FE_USD FALLBACK FLOOR APPLIED" not in captured
    assert "FE_USD AUTO_FLOOR_UPDATE" in captured
    assert cache_path.exists()


def test_fe_usd_spot_cache_upward_drift_cap(monkeypatch, tmp_path) -> None:
    """P1: upward drift cap rejects full live bump without allowing runaway cache growth."""
    import json
    import time

    bal = 0.04
    prior_spot = 2000.0
    now = time.time()
    cache_path = tmp_path / "fe_usd_spot_cache.json"
    cache_path.write_text(
        json.dumps({"WETH_ALPHA": {"spot_usd": prior_spot, "updated_unix": now}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY", 5.0)
    monkeypatch.setattr(runtime, "FE_USD_SPOT_CACHE_FILE", str(cache_path))
    asset = _FakeAsset(
        symbol="WETH_ALPHA",
        addr="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        current_price_usd=2500.0,
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [asset],
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: bal)
    # Live spot $2500/token would raise cache 25% in one tick — cap to ~5%.
    monkeypatch.setattr(
        runtime,
        "_quote_followed_token_usdt_mtm",
        lambda *_a, **_k: bal * 2500.0,
    )
    runtime._followed_equity_tokens_usdt_usd()
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    persisted = float(saved["WETH_ALPHA"]["spot_usd"])
    assert persisted == pytest.approx(prior_spot * 1.05, rel=1e-4)
    assert persisted < 2500.0


def test_capped_fe_usd_spot_persist_rejects_upward_without_live() -> None:
    """Unit: drift cap helper never raises spot when live spot is not above prior."""
    assert runtime._capped_fe_usd_spot_persist(0.0, 2000.0, 1700000000.0) == 0.0
    assert runtime._capped_fe_usd_spot_persist(1900.0, 2000.0, 1700000000.0) == 1900.0
# endregion
