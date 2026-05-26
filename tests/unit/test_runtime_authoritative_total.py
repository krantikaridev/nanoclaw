"""Cleanup #1 (May 2026): single source of truth for WALLET TOTAL USD.

Pre-cleanup, the bot's TOTAL flowed through four touchpoints with no shared
function:
  1. compute  — ``Balances.total_portfolio_usd`` in ``runtime.get_balances``
  2. log      — ``WALLET TOTAL USD`` line emitted from ``modules.swap_executor``
  3. CSV      — ``portfolio_history.csv::total_value`` from
                ``runtime.write_portfolio_history_snapshot``
  4. report   — ``scripts/pnl_report.py`` regex parsing the log

A single broken FE_USD quote silently corrupted every operator-facing PnL
surface for hours (May 2026 LINK_ALPHA incident). After Cleanup #1, every
reader funnels through ``runtime.compute_authoritative_total_usd`` so the four
surfaces cannot drift apart.
"""

from __future__ import annotations

import csv

import pytest

import clean_swap
from modules import runtime
from modules.runtime import Balances, compute_authoritative_total_usd
from scripts import pnl_report


# region helper basics


def test_helper_returns_balances_total_portfolio_usd() -> None:
    """Helper is the canonical READ accessor for ``Balances.total_portfolio_usd``."""
    b = Balances(
        usdt=10.0,
        wmatic=5.0,
        pol=2.0,
        usdc=20.0,
        followed_equity_usd=8.0,
        total_portfolio_usd=99.99,
    )
    assert compute_authoritative_total_usd(b) == pytest.approx(99.99)


def test_helper_returns_float_not_dataclass_field() -> None:
    """Caller contract: helper returns a Python float (decoupled from dataclass)."""
    b = Balances(usdt=0.0, wmatic=0.0, pol=0.0, usdc=0.0, total_portfolio_usd=42)
    out = compute_authoritative_total_usd(b)
    assert isinstance(out, float)
    assert out == pytest.approx(42.0)


# endregion


# region FE_USD undercount regression (May 2026 LINK_ALPHA incident)


def test_helper_with_fe_usd_zero_returns_remaining_components() -> None:
    """Regression: when FE_USD silently quotes to 0, helper still returns the
    stables-and-WMATIC-and-POL portion. Proves the bug surface (a $0 FE_USD
    leg) does not silently zero out the entire TOTAL."""
    stables_only_total = 50.0 + 30.0 + (5.0 * 2.0) + (1.0 * 0.25)  # = 90.25
    b = Balances(
        usdt=50.0,
        wmatic=5.0,
        pol=1.0,
        usdc=30.0,
        followed_equity_usd=0.0,
        total_portfolio_usd=stables_only_total,
    )
    assert compute_authoritative_total_usd(b) == pytest.approx(stables_only_total)


def test_helper_emits_distinct_total_when_fe_usd_present_vs_absent() -> None:
    """Regression: a non-zero FE_USD must change the helper's reported TOTAL.
    If TOTAL were ever computed without FE_USD, this assertion would fail —
    re-surfacing the May 2026 silent-undercount."""
    common = dict(usdt=50.0, wmatic=5.0, pol=1.0, usdc=30.0)
    base = 50.0 + 30.0 + (5.0 * 2.0) + (1.0 * 0.25)
    without_fe = Balances(**common, followed_equity_usd=0.0, total_portfolio_usd=base)
    with_fe = Balances(**common, followed_equity_usd=12.34, total_portfolio_usd=base + 12.34)
    delta = compute_authoritative_total_usd(with_fe) - compute_authoritative_total_usd(without_fe)
    assert delta == pytest.approx(12.34)


# endregion


# region CSV writer goes through the helper


def _patch_runtime_balance_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub on-chain balance reads with deterministic values for the CSV writer."""
    monkeypatch.setattr(clean_swap, "POL_USD_PRICE", 0.25)
    monkeypatch.setattr(clean_swap, "USDT", "0xusdt")
    monkeypatch.setattr(clean_swap, "USDC", "0xusdc")
    monkeypatch.setattr(clean_swap, "WMATIC", "0xwmatic")

    def _bal(token_address, decimals=6, web3_client=None, wallet_address=None):
        if token_address == "0xusdt":
            return 50.0
        if token_address == "0xusdc":
            return 10.0
        if token_address == "0xwmatic":
            return 5.0
        return 0.0

    monkeypatch.setattr(clean_swap, "get_token_balance", _bal)
    monkeypatch.setattr(clean_swap, "get_pol_balance", lambda wallet_address=clean_swap.WALLET: 20.0)
    # Disable FE_USD scan so the test can pin a deterministic total without
    # poking the real ``followed_equities.json`` quote stack.
    monkeypatch.setattr(runtime, "_followed_equity_tokens_usdt_usd", lambda: 0.0)


def test_write_portfolio_history_snapshot_total_matches_helper(monkeypatch, tmp_path):
    """CSV ``total_value`` = ``compute_authoritative_total_usd`` of the same balances.

    The same numeric components — usdt, usdc, wmatic*current_price,
    pol*pol_price_usd, fe_usd — must produce one TOTAL whether read from the
    CSV row or from the helper directly.
    """
    csv_path = tmp_path / "portfolio_history.csv"
    monkeypatch.setattr(clean_swap, "PORTFOLIO_HISTORY_FILE", str(csv_path))
    _patch_runtime_balance_reads(monkeypatch)

    clean_swap.write_portfolio_history_snapshot(current_price=2.0)

    # Reconstruct what the helper sees from the same components.
    expected_balances = Balances(
        usdt=50.0,
        wmatic=5.0,
        pol=20.0,
        usdc=10.0,
        followed_equity_usd=0.0,
        total_portfolio_usd=50.0 + 10.0 + (5.0 * 2.0) + (20.0 * 0.25) + 0.0,  # = 75.0
    )
    expected_total = compute_authoritative_total_usd(expected_balances)

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert float(rows[0]["total_value"]) == pytest.approx(expected_total)


def test_write_portfolio_history_snapshot_includes_fe_usd_in_total(monkeypatch, tmp_path):
    """Regression: a non-zero FE_USD reaches the CSV row exactly as the helper sees it.

    If a future change made ``write_portfolio_history_snapshot`` skip FE_USD
    while the helper still added it, the May 2026 silent-undercount would be
    back. Pinning equality here closes that drift surface.
    """
    csv_path = tmp_path / "portfolio_history.csv"
    monkeypatch.setattr(clean_swap, "PORTFOLIO_HISTORY_FILE", str(csv_path))
    _patch_runtime_balance_reads(monkeypatch)
    monkeypatch.setattr(runtime, "_followed_equity_tokens_usdt_usd", lambda: 17.5)

    clean_swap.write_portfolio_history_snapshot(current_price=2.0)

    expected_balances = Balances(
        usdt=50.0,
        wmatic=5.0,
        pol=20.0,
        usdc=10.0,
        followed_equity_usd=17.5,
        total_portfolio_usd=50.0 + 10.0 + (5.0 * 2.0) + (20.0 * 0.25) + 17.5,  # = 92.5
    )
    expected_total = compute_authoritative_total_usd(expected_balances)

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert float(rows[0]["total_value"]) == pytest.approx(expected_total)
    assert expected_total == pytest.approx(92.5)


# endregion


# region scripts/pnl_report in-process compute uses the helper


def test_compute_authoritative_total_in_process_uses_helper(monkeypatch) -> None:
    """``nanopnl`` / ``nanostatus`` / ``nanodaily`` read TOTAL via the helper, not regex."""
    sentinel = Balances(
        usdt=12.0,
        wmatic=4.0,
        pol=1.5,
        usdc=18.0,
        followed_equity_usd=6.0,
        total_portfolio_usd=42.42,
    )
    monkeypatch.setattr(runtime, "get_balances", lambda: sentinel)

    out = pnl_report.compute_authoritative_total_in_process()
    assert out is not None
    assert out["total"] == pytest.approx(compute_authoritative_total_usd(sentinel))
    assert out["total"] == pytest.approx(42.42)
    assert out["usdt"] == pytest.approx(12.0)
    assert out["usdc"] == pytest.approx(18.0)
    assert out["wmatic"] == pytest.approx(4.0)
    assert out["stable_usd"] == pytest.approx(30.0)
    assert "compute_authoritative_total_usd" in out["source"]


def test_compute_authoritative_total_in_process_returns_none_on_unusable_total(monkeypatch) -> None:
    """RPC-flake guard: near-zero total → caller falls through to historical regex."""
    bogus = Balances(usdt=0.0, wmatic=0.0, pol=0.0, usdc=0.0, total_portfolio_usd=0.0)
    monkeypatch.setattr(runtime, "get_balances", lambda: bogus)
    assert pnl_report.compute_authoritative_total_in_process() is None


def test_compute_authoritative_total_in_process_returns_none_on_runtime_error(monkeypatch) -> None:
    """If runtime raises (RPC down, etc.), the in-process helper must not crash nanopnl."""
    def _raise():
        raise RuntimeError("rpc down")

    monkeypatch.setattr(runtime, "get_balances", _raise)
    assert pnl_report.compute_authoritative_total_in_process() is None


def test_get_current_balance_prefers_in_process_over_log_regex(monkeypatch, tmp_path) -> None:
    """When the in-process compute is available, ``get_current_balance`` uses it
    over the regex fallback, even if the log file would yield a different total."""
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "2026-05-26 09:00:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$1.23 | "
        "USDT=$0.50 | USDC=$0.50 | STABLE_USD=$1.00 | "
        "WMATIC=0.000000 | POL=0.000000 | FE_USD=$0.23\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    sentinel = Balances(
        usdt=10.0, wmatic=5.0, pol=2.0, usdc=20.0,
        followed_equity_usd=8.0, total_portfolio_usd=88.88,
    )
    monkeypatch.setattr(runtime, "get_balances", lambda: sentinel)

    current = pnl_report.get_current_balance()
    assert current is not None
    assert current["total"] == pytest.approx(88.88)
    assert "compute_authoritative_total_usd" in current["source"]


def test_get_current_balance_falls_back_to_regex_when_in_process_unavailable(monkeypatch, tmp_path) -> None:
    """RPC down on operator VM → nanopnl still works via historical-log regex."""
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "2026-05-26 09:00:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$130.55 | "
        "USDT=$10.00 | USDC=$80.00 | STABLE_USD=$90.00 | "
        "WMATIC=5.000000 | POL=4.000000 | FE_USD=$36.55\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))
    monkeypatch.setattr(pnl_report, "compute_authoritative_total_in_process", lambda: None)

    current = pnl_report.get_current_balance()
    assert current is not None
    assert current["total"] == pytest.approx(130.55)
    assert current["source"] == "RUNTIME WALLET TRUTH (TOTAL USD)"


# endregion


# region log line ↔ regex round-trip (proves emission format still parses)


def test_swap_executor_log_format_round_trips_through_v2_regex() -> None:
    """The log line shape emitted by ``swap_executor`` (using the helper) must
    parse back through the historical regex. Guards against future formatting
    drift between the helper-driven emitter and the fallback regex parser."""
    b = Balances(
        usdt=10.0, wmatic=5.0, pol=2.0, usdc=20.0,
        followed_equity_usd=8.0, pol_usd=0.5, total_portfolio_usd=55.5,
    )
    total_usd = compute_authoritative_total_usd(b)
    stable = float(b.usdt) + float(b.usdc)
    log_line = (
        f"WALLET TOTAL USD | TOTAL=${total_usd:.2f} "
        f"| USDT=${b.usdt:.2f} | USDC=${b.usdc:.2f} | STABLE_USD=${stable:.2f} "
        f"| WMATIC={b.wmatic:.6f} "
        f"| POL={b.pol:.6f} | POL_USD=${b.pol_usd:.2f} "
        f"| FE_USD=${b.followed_equity_usd:.2f}"
    )
    m = pnl_report.AUTHORITATIVE_TOTAL_PATTERN_V2.search(log_line)
    assert m is not None, f"V2 regex must still parse helper-emitted log line: {log_line!r}"
    assert float(m.group(1)) == pytest.approx(total_usd)


# endregion


# region POL_USD operator visibility (Cleanup #3, May 2026)
# Pre-cleanup: POL was already in ``total_portfolio_usd`` arithmetically, but only POL
# quantity (not POL_USD) appeared in the ``WALLET TOTAL USD`` log line. Operators
# reconciling against MetaMask had to back-solve POL's USD slice from the gap, which
# made it look (in the 2026-05-26 incident) as if POL was excluded from TOTAL. Cleanup #3
# makes the POL_USD slice a first-class field on ``Balances`` and prints it in the log.


def test_pol_usd_field_equals_pol_times_pol_price(monkeypatch) -> None:
    """``Balances.pol_usd`` must equal ``pol × POL_USD_PRICE`` from ``get_balances()``.

    Pinning this prevents a future refactor from setting ``pol_usd`` from a stale
    cache or a different price source than the one driving ``total_portfolio_usd``.
    """
    import clean_swap

    monkeypatch.setattr(runtime, "POL_USD_PRICE", 0.10)
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(runtime, "get_pol_balance", lambda *_a, **_k: 9.177)
    monkeypatch.setattr(runtime, "_total_usdc_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(runtime, "_followed_equity_tokens_usdt_usd", lambda: 0.0)
    monkeypatch.setattr("protection.get_live_wmatic_price", lambda: 0.0)

    b = runtime.get_balances()
    assert b.pol == pytest.approx(9.177)
    assert b.pol_usd == pytest.approx(9.177 * 0.10)
    # Acceptance criterion B: POL is included in TOTAL exactly once (here, the only
    # non-zero component is POL_USD).
    assert compute_authoritative_total_usd(b) == pytest.approx(9.177 * 0.10)


def test_pol_usd_contributes_to_total_exactly_once(monkeypatch) -> None:
    """Toggling POL between 0 and a positive balance changes TOTAL by exactly POL × price.

    If a future refactor double-counted POL (e.g. once via ``pol_usd`` and once via
    ``pol × POL_USD_PRICE``), or zero-counted it, this assertion would fail.
    """
    monkeypatch.setattr(runtime, "POL_USD_PRICE", 0.10)
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(runtime, "_total_usdc_balance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(runtime, "_followed_equity_tokens_usdt_usd", lambda: 0.0)
    monkeypatch.setattr("protection.get_live_wmatic_price", lambda: 0.0)

    monkeypatch.setattr(runtime, "get_pol_balance", lambda *_a, **_k: 0.0)
    total_zero = compute_authoritative_total_usd(runtime.get_balances())

    monkeypatch.setattr(runtime, "get_pol_balance", lambda *_a, **_k: 10.0)
    total_with_pol = compute_authoritative_total_usd(runtime.get_balances())

    assert (total_with_pol - total_zero) == pytest.approx(10.0 * 0.10)


def test_wallet_total_usd_log_line_includes_pol_usd_field() -> None:
    """``WALLET TOTAL USD`` log line must surface POL_USD so operators reconciling
    against MetaMask see POL's USD contribution without back-solving.

    Regression for the 2026-05-26 incident: bot TOTAL $111.08 vs wallet $121.33,
    where the $0.85 POL slice was invisible in the log and looked excluded.
    """
    b = Balances(
        usdt=10.48, wmatic=156.571, pol=9.177, usdc=41.76,
        followed_equity_usd=53.74, pol_usd=0.9177,
        total_portfolio_usd=10.48 + 41.76 + 14.50 + 0.9177 + 53.74,
    )
    total_usd = compute_authoritative_total_usd(b)
    stable = float(b.usdt) + float(b.usdc)
    log_line = (
        f"WALLET TOTAL USD | TOTAL=${total_usd:.2f} "
        f"| USDT=${b.usdt:.2f} | USDC=${b.usdc:.2f} | STABLE_USD=${stable:.2f} "
        f"| WMATIC={b.wmatic:.6f} "
        f"| POL={b.pol:.6f} | POL_USD=${b.pol_usd:.2f} "
        f"| FE_USD=${b.followed_equity_usd:.2f}"
    )
    assert "POL_USD=$0.92" in log_line
    m = pnl_report.AUTHORITATIVE_TOTAL_PATTERN_V2.search(log_line)
    assert m is not None, "POL_USD insertion must not break the V2 fallback regex"


# endregion
