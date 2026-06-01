"""Unit tests for scripts.pnl_report snapshot extraction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts import pnl_report
from scripts.pnl_report import extract_snapshots


@pytest.fixture(autouse=True)
def _disable_in_process_authoritative_total(monkeypatch):
    """Force regex-fallback path for legacy tests.

    Cleanup #1 (May 2026): ``get_current_balance`` now prefers the in-process
    ``compute_authoritative_total_in_process`` (live RPC via runtime). The tests
    in this module pin the regex / log-snapshot semantics, so we disable the
    in-process path here. New tests covering the authoritative in-process path
    live in ``test_runtime_authoritative_total.py``.
    """
    monkeypatch.setattr(
        pnl_report,
        "compute_authoritative_total_in_process",
        lambda: None,
    )


def _write_log(tmp_path: Path, body: str) -> Path:
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(body, encoding="utf-8")
    return log_file


def test_extract_snapshots_discards_stale_wallet_balance(tmp_path: Path) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-04 10:00:00 [nanoclaw] WALLET BALANCE | USDC=100.00",
                "line 2",
                "line 3",
                "line 4",
                "line 5",
                "line 6",
                "line 7",
                "line 8",
                "2026-05-04 10:10:00 Real USDT: 1.00 | USDC: 90.00 | WMATIC: 9.00",
            ]
        ),
    )

    snapshots = extract_snapshots(log_file)

    assert len(snapshots) == 1
    assert snapshots[0].source == "real"
    assert snapshots[0].usdc == 90.00
    assert snapshots[0].usdt == 1.00
    assert snapshots[0].wmatic == 9.00


def test_extract_snapshots_pairs_recent_wallet_balance_with_real_line(tmp_path: Path) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-04 10:00:00 [nanoclaw] WALLET BALANCE | USDC=102.87",
                "debug line",
                "2026-05-04 10:00:03 Real USDT: 0.00 | USDC: 101.10 | WMATIC: 2.50",
            ]
        ),
    )

    snapshots = extract_snapshots(log_file)

    assert len(snapshots) == 1
    assert snapshots[0].source == "paired"
    # wallet balance takes precedence when the pair is fresh
    assert snapshots[0].usdc == 102.87
    assert snapshots[0].usdt == 0.00
    assert snapshots[0].wmatic == 2.50


def test_extract_snapshots_discards_orphan_wallet_balance_at_eof(tmp_path: Path) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-04 10:00:00 [nanoclaw] WALLET BALANCE | USDC=111.11",
                "debug line",
                "another debug line",
            ]
        ),
    )

    snapshots = extract_snapshots(log_file)

    assert snapshots == []


def test_extract_snapshots_parses_authoritative_runtime_total_line(tmp_path: Path) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-06 10:00:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$145.25 | USDT=$10.00 | USDC=$80.00 | WMATIC=25.123456 | POL=4.000000 | FE_USD=$12.34",
            ]
        ),
    )

    snapshots = extract_snapshots(log_file)

    assert len(snapshots) == 1
    assert snapshots[0].source == "authoritative_total"
    assert snapshots[0].total == 145.25
    assert snapshots[0].usdt == 10.0
    assert snapshots[0].usdc == 80.0
    assert snapshots[0].wmatic == 25.123456
    assert snapshots[0].stable_usd_hint is None


def test_extract_snapshots_parses_authoritative_v2_stable_usd_hint(tmp_path: Path) -> None:
    body = (
        "2026-05-06 11:00:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$101.49 | "
        "USDT=$25.09 | USDC=$25.76 | STABLE_USD=$50.85 | "
        "WMATIC=363.364463 | POL=1.215000 | FE_USD=$14.79"
    )
    log_file = _write_log(tmp_path, body)

    snapshots = extract_snapshots(log_file)

    assert len(snapshots) == 1
    assert snapshots[0].stable_usd_hint == pytest.approx(50.85)
    assert snapshots[0].usdt == pytest.approx(25.09)
    assert snapshots[0].usdc == pytest.approx(25.76)


def test_get_current_balance_rpc_read_suspect_when_stables_near_zero_but_total_high(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-06 11:05:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$60.00 | "
                "USDT=$0.10 | USDC=$0.00 | STABLE_USD=$0.10 | "
                "WMATIC=363.364463 | POL=1.20 | FE_USD=$0.00",
            ]
        ),
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    current = pnl_report.get_current_balance()
    assert current is not None
    assert current["rpc_read_suspect"] is True
    assert current["stable_usd"] == pytest.approx(0.1)


def test_get_current_balance_prefers_live_onchain_snapshot_over_manual(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "[2026-05-04 10:00:00] MANUAL CORRECT BALANCE | USDC=$66.00 | WMATIC=$4.00 | USDT=$30.00 | TOTAL=$100.00 | Source=MetaMask",
                "2026-05-04 10:01:00 Real USDT: 10.00 | USDC: 80.00 | WMATIC: 5.00",
                "[2026-05-04 10:02:00] MANUAL CORRECT BALANCE | USDC=$67.00 | WMATIC=$4.00 | USDT=$31.00 | TOTAL=$102.00 | Source=AutoLogger",
            ]
        ),
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    current = pnl_report.get_current_balance()

    assert current is not None
    assert current["source"] == "ON-CHAIN LIVE (Real USDT line)"
    assert current["total"] == 95.0


def test_get_current_balance_prefers_authoritative_total_over_legacy_live(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-04 10:01:00 Real USDT: 10.00 | USDC: 80.00 | WMATIC: 5.00",
                "2026-05-04 10:02:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$130.55 | USDT=$10.00 | USDC=$80.00 | WMATIC=5.000000 | POL=4.000000 | FE_USD=$36.55",
            ]
        ),
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    current = pnl_report.get_current_balance()

    assert current is not None
    assert current["source"] == "RUNTIME WALLET TRUTH (TOTAL USD)"
    assert current["total"] == 130.55
    assert current["stable_usd"] == pytest.approx(90.0)
    assert current["rpc_read_suspect"] is False


def test_get_current_balance_uses_most_recent_snapshot_within_best_rank(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-04 10:00:00 [nanoclaw] WALLET BALANCE | USDC=60.00",
                "2026-05-04 10:00:03 Real USDT: 10.00 | USDC: 50.00 | WMATIC: 5.00",
                "2026-05-04 10:10:00 [nanoclaw] WALLET BALANCE | USDC=90.00",
                "2026-05-04 10:10:03 Real USDT: 20.00 | USDC: 80.00 | WMATIC: 4.00",
            ]
        ),
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    current = pnl_report.get_current_balance()

    assert current is not None
    assert current["source"] == "ON-CHAIN LIVE (WALLET+REAL paired)"
    # Latest live snapshot should win: USDT 20 + USDC 90 + WMATIC 4
    assert current["total"] == 114.0


def test_get_current_balance_prefers_newer_real_over_older_paired(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-04 10:00:00 [nanoclaw] WALLET BALANCE | USDC=60.00",
                "2026-05-04 10:00:01 Real USDT: 10.00 | USDC: 50.00 | WMATIC: 5.00",
                # Later cycle has only direct real line (no wallet pair).
                "2026-05-04 10:05:00 Real USDT: 21.00 | USDC: 81.00 | WMATIC: 4.00",
            ]
        ),
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    current = pnl_report.get_current_balance()

    assert current is not None
    assert current["source"] == "ON-CHAIN LIVE (Real USDT line)"
    assert current["total"] == 106.0


def test_get_current_balance_keeps_live_snapshot_when_wmatic_is_high(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                # Legitimate high-WMATIC live holding should remain eligible.
                "2026-05-04 10:05:00 Real USDT: 20.00 | USDC: 80.00 | WMATIC: 25.00",
                # Newer manual correction should not override live snapshot preference.
                "[2026-05-04 10:06:00] MANUAL CORRECT BALANCE | USDC=$67.00 | WMATIC=$4.00 | USDT=$31.00 | TOTAL=$102.00 | Source=AutoLogger",
            ]
        ),
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    current = pnl_report.get_current_balance()

    assert current is not None
    assert current["source"] == "ON-CHAIN LIVE (Real USDT line)"
    assert current["wmatic"] == 25.0
    assert current["total"] == 125.0


def test_get_current_balance_discards_unreasonable_live_snapshot_and_falls_back(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                # Corrupted/unreasonable WMATIC value should be rejected by sanity guard.
                "2026-05-04 10:05:00 Real USDT: 20.00 | USDC: 80.00 | WMATIC: 99999999.00",
                "[2026-05-04 10:06:00] MANUAL CORRECT BALANCE | USDC=$67.00 | WMATIC=$4.00 | USDT=$31.00 | TOTAL=$102.00 | Source=AutoLogger",
            ]
        ),
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))

    current = pnl_report.get_current_balance()

    assert current is not None
    assert current["source"] == "MANUAL (AutoLogger)"
    assert current["total"] == 102.0


def test_is_usable_snapshot_rejects_nan_component() -> None:
    snap = pnl_report.BalanceSnapshot(
        usdt=float("nan"),
        usdc=10.0,
        wmatic=1.0,
        total=11.0,
        source="real",
    )
    assert pnl_report._is_usable_snapshot(snap) is False


def test_is_usable_snapshot_rejects_infinite_component() -> None:
    snap = pnl_report.BalanceSnapshot(
        usdt=float("inf"),
        usdc=10.0,
        wmatic=1.0,
        total=11.0,
        source="real",
    )
    assert pnl_report._is_usable_snapshot(snap) is False


def test_is_usable_snapshot_rejects_negative_component() -> None:
    snap = pnl_report.BalanceSnapshot(
        usdt=10.0,
        usdc=10.0,
        wmatic=-0.5,
        total=19.5,
        source="real",
    )
    assert pnl_report._is_usable_snapshot(snap) is False


def test_resolve_session_baseline_creates_and_resets(tmp_path: Path, monkeypatch) -> None:
    baseline_file = tmp_path / "portfolio_session_baseline.json"
    monkeypatch.setattr(pnl_report, "SESSION_BASELINE_FILE", str(baseline_file))

    first_total, _ = pnl_report.resolve_session_baseline(100.0, reset=False)
    assert first_total == 100.0
    second_total, _ = pnl_report.resolve_session_baseline(120.0, reset=False)
    assert second_total == 100.0

    reset_total, _ = pnl_report.resolve_session_baseline(120.0, reset=True)
    assert reset_total == 120.0


def test_resolve_24h_baseline_uses_latest_value_before_cutoff(tmp_path: Path, monkeypatch) -> None:
    csv_file = tmp_path / "portfolio_history.csv"
    csv_file.write_text(
        "\n".join(
            [
                "timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value",
                "2026-05-01T00:00:00+00:00,1,1,1,1,0.1,90",
                "2026-05-04T12:00:00+00:00,1,1,1,1,0.1,100",
                "2026-05-05T13:00:00+00:00,1,1,1,1,0.1,130",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))

    class _FakeDateTime:
        @staticmethod
        def now(tz):
            from datetime import datetime

            return datetime(2026, 5, 6, 0, 0, 0, tzinfo=tz)

        @staticmethod
        def fromisoformat(raw):
            from datetime import datetime

            return datetime.fromisoformat(raw)

    monkeypatch.setattr(pnl_report, "datetime", _FakeDateTime)

    baseline = pnl_report.resolve_24h_baseline(140.0)
    assert baseline == 100.0


def test_parse_lookback_windows_default_and_tokens() -> None:
    assert pnl_report.parse_lookback_windows("") == [("24h", 24.0)]
    assert pnl_report.parse_lookback_windows("  ") == [("24h", 24.0)]
    w = {label: hrs for label, hrs in pnl_report.parse_lookback_windows("1h,1d,2w,1m")}
    assert w["1h"] == pytest.approx(1.0)
    assert w["1d"] == pytest.approx(24.0)
    assert w["2w"] == pytest.approx(336.0)
    assert w["1m"] == pytest.approx(720.0)


def test_resolve_history_at_or_before_returns_timestamp(tmp_path: Path, monkeypatch) -> None:
    csv_file = tmp_path / "portfolio_history.csv"
    csv_file.write_text(
        "\n".join(
            [
                "timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value",
                "2026-05-05T10:00:00+00:00,1,1,1,1,0.1,80",
                "2026-05-05T14:00:00+00:00,1,1,1,1,0.1,85",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    cutoff = pnl_report.datetime(2026, 5, 5, 15, 0, 0, tzinfo=pnl_report.timezone.utc)
    total, ts = pnl_report._resolve_history_at_or_before(cutoff)
    assert total == pytest.approx(85.0)
    assert ts == pnl_report.datetime(2026, 5, 5, 14, 0, 0, tzinfo=pnl_report.timezone.utc)


def test_print_daily_summary_emits_lookback_block(tmp_path: Path, monkeypatch, capsys) -> None:
    from datetime import datetime, timezone

    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "2026-05-06 10:02:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$90.00 | USDT=$10.00 | "
        "USDC=$80.00 | STABLE_USD=$90.00 | WMATIC=0.000000 | POL=0 | FE_USD=$0\n",
        encoding="utf-8",
    )
    csv_file = tmp_path / "portfolio_history.csv"
    csv_file.write_text(
        "\n".join(
            [
                "timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value",
                "2026-05-05T00:00:00+00:00,1,1,1,1,0.1,100",
                "2026-05-06T10:00:00+00:00,1,1,1,1,0.1,95",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    monkeypatch.setattr(pnl_report, "SESSION_BASELINE_FILE", str(tmp_path / "portfolio_session_baseline.json"))

    fixed_now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fixed_now

        @staticmethod
        def fromisoformat(raw):
            text = str(raw or "").strip()
            return datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)

    monkeypatch.setattr(pnl_report, "datetime", _FakeDateTime)

    def _fixed_baseline(total: float) -> float:
        return 100.0

    monkeypatch.setattr(pnl_report, "resolve_portfolio_baseline_usd", _fixed_baseline)

    pnl_report.print_daily_summary(lookback="24h")
    out = capsys.readouterr().out
    assert "📅 LOOKBACK" in out
    assert "ref $100.00" in out
    assert "📈 TREND" in out
    assert "▁" in out or "█" in out or "▄" in out


def test_render_ascii_sparkline_scales_range() -> None:
    s = pnl_report.render_ascii_sparkline([10.0, 11.0, 15.0, 19.0, 20.0], width=16)
    assert len(s) == 16
    assert pnl_report._SPARK_BLOCKS[0] in s and pnl_report._SPARK_BLOCKS[-1] in s


def test_load_portfolio_total_series_sorted_and_dedupes_same_ts(tmp_path: Path, monkeypatch) -> None:
    csv_file = tmp_path / "portfolio_history.csv"
    csv_file.write_text(
        "\n".join(
            [
                "timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value",
                "2026-05-05T12:00:01+00:00,1,1,1,1,0.1,90",
                "2026-05-05T10:00:00+00:00,1,1,1,1,0.1,80",
                "2026-05-05T12:00:01+00:00,1,1,1,1,0.1,95",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    series = pnl_report.load_portfolio_total_series()
    assert len(series) == 2
    assert series[0][1] == pytest.approx(80.0)
    assert series[1][1] == pytest.approx(95.0)


def test_count_velocity_fills_utc_day_window(tmp_path: Path) -> None:
    day = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    inside = int(day_start.timestamp()) + 3600
    outside = int(day_end.timestamp()) + 60
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {inside} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "✅ Swap executed successfully!",
                f"[nanoclaw] === CYCLE {outside} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "✅ Swap executed successfully!",
            ]
        ),
    )
    assert (
        pnl_report.count_velocity_fills(log_file, since_utc=day_start, until_utc=day_end) == 1
    )


def test_count_velocity_fills_session_since(tmp_path: Path) -> None:
    session_start = datetime(2026, 5, 26, 18, 21, 34, tzinfo=timezone.utc)
    before = int(session_start.timestamp()) - 900
    after = int(session_start.timestamp()) + 900
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {before} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "✅ Swap executed successfully!",
                f"[nanoclaw] === CYCLE {after} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "✅ Swap executed successfully!",
            ]
        ),
    )
    assert pnl_report.count_velocity_fills(log_file, since_utc=session_start) == 1


def test_format_velocity_lines_includes_session(tmp_path: Path, monkeypatch) -> None:
    log_file = _write_log(tmp_path, "")
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))
    now = datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
    lines = pnl_report.format_velocity_lines(
        log_path=log_file,
        session_started_at="2026-05-26T18:21:34+00:00",
        now_utc=now,
    )
    assert any("velocity_fills_per_day_utc=" in x for x in lines)
    assert any("velocity_fills_session=" in x for x in lines)


def _attribution_line(tx: str, sz: float) -> str:
    return (
        f"[nanoclaw] TRADE_ATTRIBUTION tx={tx} dir=USDC→WMATIC "
        f"sz≈{sz:.2f} msg=Swap executed successfully!"
    )


def test_sum_turnover_usd_utc_day_window(tmp_path: Path) -> None:
    day = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    inside = int(day_start.timestamp()) + 3600
    outside = int(day_end.timestamp()) + 60
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {inside} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                _attribution_line("0xabc111", 30.0),
                f"[nanoclaw] === CYCLE {outside} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                _attribution_line("0xabc222", 50.0),
            ]
        ),
    )
    notional, tx_count = pnl_report.sum_turnover_usd(
        log_file, since_utc=day_start, until_utc=day_end
    )
    assert notional == pytest.approx(30.0)
    assert tx_count == 1


def test_sum_turnover_usd_session_since(tmp_path: Path) -> None:
    session_start = datetime(2026, 5, 26, 18, 21, 34, tzinfo=timezone.utc)
    before = int(session_start.timestamp()) - 900
    after = int(session_start.timestamp()) + 900
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {before} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                _attribution_line("0xabc111", 20.0),
                f"[nanoclaw] === CYCLE {after} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                _attribution_line("0xabc222", 40.0),
            ]
        ),
    )
    notional, tx_count = pnl_report.sum_turnover_usd(log_file, since_utc=session_start)
    assert notional == pytest.approx(40.0)
    assert tx_count == 1


def test_sum_turnover_usd_dedupes_same_tx(tmp_path: Path) -> None:
    ts = int(datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                _attribution_line("0xabc333", 25.0),
                _attribution_line("0xabc333", 25.0),
            ]
        ),
    )
    notional, tx_count = pnl_report.sum_turnover_usd(log_file)
    assert notional == pytest.approx(25.0)
    assert tx_count == 1


def test_sum_turnover_usd_ignores_plan_only_attribution(tmp_path: Path) -> None:
    ts = int(datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "TRADE_ATTRIBUTION | Asset=LINK | Size=$15.00 | Signal=0.81 | Plan only",
                _attribution_line("0xabc444", 15.0),
            ]
        ),
    )
    notional, tx_count = pnl_report.sum_turnover_usd(log_file)
    assert notional == pytest.approx(15.0)
    assert tx_count == 1


def test_sum_turnover_usd_ignores_wei_misattribution(tmp_path: Path) -> None:
    ts = int(datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                _attribution_line("0xabc666", 5e19),
                _attribution_line("0xabc777", 12.5),
            ]
        ),
    )
    notional, tx_count = pnl_report.sum_turnover_usd(log_file)
    assert notional == pytest.approx(12.5)
    assert tx_count == 1


def test_format_turnover_lines_includes_session(tmp_path: Path) -> None:
    day = datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    inside = int(day_start.timestamp()) + 3600
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {inside} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                _attribution_line("0xabc555", 60.0),
            ]
        ),
    )
    lines = pnl_report.format_turnover_lines(
        log_path=log_file,
        session_started_at="2026-05-26T18:21:34+00:00",
        seed_usd=120.0,
        now_utc=day,
    )
    assert any("turnover_notional_usd_day_utc=60.00" in x for x in lines)
    assert any("turnover_multiple_day_utc=0.50x" in x for x in lines)
    assert any("turnover_notional_usd_session=" in x for x in lines)
    assert any("turnover_multiple_session=" in x for x in lines)


def test_parse_trade_skip_reason_colon_and_pipe() -> None:
    assert pnl_report.parse_trade_skip_reason(
        "[nanoclaw] TRADE SKIPPED: cooldown (global, ~130s left)"
    ) == "cooldown"
    assert pnl_report.parse_trade_skip_reason(
        "[nanoclaw] TRADE SKIPPED: defensive_pause (risk=HIGH) — pausing X-signal BUY entries"
    ) == "defensive_pause"
    assert pnl_report.parse_trade_skip_reason(
        "[nanoclaw] TRADE SKIPPED | below minimum size | direction=BUY | size=$1.00"
    ) == "below minimum size"
    assert pnl_report.parse_trade_skip_reason("no skip here") is None


def test_count_trade_skips_lifetime_and_24h_window(tmp_path: Path) -> None:
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    inside = int((now - timedelta(hours=2)).timestamp())
    outside = int((now - timedelta(hours=30)).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {outside} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "[nanoclaw] TRADE SKIPPED: cooldown (global, ~130s left)",
                f"[nanoclaw] === CYCLE {inside} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "[nanoclaw] TRADE SKIPPED: defensive_pause (risk=HIGH)",
                "[nanoclaw] TRADE SKIPPED | below minimum size | direction=BUY",
            ]
        ),
    )
    assert pnl_report.count_trade_skips(log_file) == 3
    assert pnl_report.count_trade_skips(log_file, since_utc=since, until_utc=now) == 2


def test_trade_skip_reason_counts_top_reasons(tmp_path: Path) -> None:
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    ts = int((now - timedelta(hours=1)).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "[nanoclaw] TRADE SKIPPED: cooldown (global, ~130s left)",
                "[nanoclaw] TRADE SKIPPED: cooldown (global, ~90s left)",
                "[nanoclaw] TRADE SKIPPED: dust_deferred (below min)",
            ]
        ),
    )
    counts = pnl_report.trade_skip_reason_counts(log_file, since_utc=since, until_utc=now)
    assert counts == {"cooldown": 2, "dust_deferred": 1}


def test_format_trade_skip_stats_includes_top_reasons(tmp_path: Path) -> None:
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    ts = int((now - timedelta(hours=1)).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "[nanoclaw] TRADE SKIPPED: cooldown (global, ~130s left)",
                "[nanoclaw] TRADE SKIPPED: cooldown (global, ~90s left)",
                "[nanoclaw] TRADE SKIPPED: dust_deferred (below min)",
            ]
        ),
    )
    lines = pnl_report.format_trade_skip_stats(log_file, now_utc=now, top_n=2)
    assert lines[0] == "Trade skips (lifetime): 3"
    assert lines[1] == "Trade skips (24h UTC): 3"
    assert lines[2] == "Top skip reasons (24h): cooldown (2), dust_deferred (1)"


def test_monthly_opex_usd_sums_env(monkeypatch) -> None:
    monkeypatch.setenv("OPEX_MONTHLY_USD", "10")
    monkeypatch.setenv("HOSTING_MONTHLY_USD", "5.5")
    assert pnl_report.monthly_opex_usd() == pytest.approx(15.5)


def test_monthly_opex_usd_treats_invalid_as_zero(monkeypatch) -> None:
    monkeypatch.setenv("OPEX_MONTHLY_USD", "not-a-number")
    monkeypatch.setenv("HOSTING_MONTHLY_USD", "-3")
    assert pnl_report.monthly_opex_usd() == pytest.approx(0.0)


def test_prorate_opex_to_session_scales_by_elapsed_days(monkeypatch) -> None:
    monkeypatch.setenv("OPEX_MONTHLY_USD", "30")
    monkeypatch.setenv("HOSTING_MONTHLY_USD", "0")
    session_start = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = session_start + timedelta(days=15)
    prorated, elapsed_days, monthly = pnl_report.prorate_opex_to_session(
        session_start.isoformat(),
        now_utc=now,
    )
    assert monthly == pytest.approx(30.0)
    assert elapsed_days == pytest.approx(15.0)
    assert prorated == pytest.approx(15.0)


def test_compute_net_after_opex_subtracts_prorated_opex(monkeypatch) -> None:
    monkeypatch.setenv("OPEX_MONTHLY_USD", "30")
    monkeypatch.setenv("HOSTING_MONTHLY_USD", "0")
    session_start = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = session_start + timedelta(days=15)
    info = pnl_report.compute_net_after_opex(
        20.0,
        session_start.isoformat(),
        now_utc=now,
    )
    assert info["prorated_opex"] == pytest.approx(15.0)
    assert info["net_after_opex"] == pytest.approx(5.0)


def test_format_net_after_opex_line_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("OPEX_MONTHLY_USD", raising=False)
    monkeypatch.delenv("HOSTING_MONTHLY_USD", raising=False)
    line = pnl_report.format_net_after_opex_line(
        10.0,
        "2026-05-01T00:00:00+00:00",
    )
    assert "n/a" in line
    assert "OPEX_MONTHLY_USD" in line


def test_format_net_after_opex_line_matches_nanodaily_contract(monkeypatch) -> None:
    monkeypatch.setenv("OPEX_MONTHLY_USD", "10")
    monkeypatch.setenv("HOSTING_MONTHLY_USD", "0")
    session_start = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = session_start + timedelta(days=3)
    line = pnl_report.format_net_after_opex_line(
        5.0,
        session_start.isoformat(),
        now_utc=now,
    )
    assert line == "Net after opex (est): $+4.00 (session) | opex_budget=$10.00/mo prorated"


def test_print_daily_summary_includes_net_after_opex(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from datetime import datetime, timezone

    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "2026-05-06 10:02:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$90.00 | USDT=$10.00 | "
        "USDC=$80.00 | STABLE_USD=$90.00 | WMATIC=0.000000 | POL=0 | FE_USD=$0\n",
        encoding="utf-8",
    )
    csv_file = tmp_path / "portfolio_history.csv"
    csv_file.write_text(
        "\n".join(
            [
                "timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value",
                "2026-05-05T00:00:00+00:00,1,1,1,1,0.1,100",
            ]
        ),
        encoding="utf-8",
    )
    session_file = tmp_path / "portfolio_session_baseline.json"
    session_file.write_text(
        json.dumps(
            {
                "session_start_total": 85.0,
                "session_started_at": "2026-05-05T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    monkeypatch.setattr(pnl_report, "SESSION_BASELINE_FILE", str(session_file))
    monkeypatch.setenv("OPEX_MONTHLY_USD", "30")
    monkeypatch.setenv("HOSTING_MONTHLY_USD", "0")

    fixed_now = datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fixed_now

        @staticmethod
        def fromisoformat(raw):
            text = str(raw or "").strip()
            return datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)

    monkeypatch.setattr(pnl_report, "datetime", _FakeDateTime)
    monkeypatch.setattr(pnl_report, "resolve_portfolio_baseline_usd", lambda total: 100.0)

    pnl_report.print_daily_summary(lookback="24h")
    out = capsys.readouterr().out
    assert "Net after opex (est):" in out
    assert "opex_budget=$30.00/mo prorated" in out


def test_max_fe_spot_cache_session_pct_move_detects_large_drift(tmp_path: Path) -> None:
    session_start = datetime(2026, 5, 30, 0, 0, 0, tzinfo=timezone.utc)
    before_ts = int((session_start - timedelta(hours=12)).timestamp())
    after_ts = int((session_start + timedelta(hours=6)).timestamp())
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "\n".join(
            [
                f"=== CYCLE {before_ts}",
                "[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2500.0000 | json_floor=2500.0000 | effective_floor=2500.0000",
                f"=== CYCLE {after_ts}",
                "[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2022.0000 | json_floor=2500.0000 | effective_floor=2022.0000",
            ]
        ),
        encoding="utf-8",
    )
    cache_file = tmp_path / "fe_usd_spot_cache.json"
    cache_file.write_text(
        json.dumps({"WETH_ALPHA": {"spot_usd": 2022.0, "updated_unix": float(after_ts)}}),
        encoding="utf-8",
    )
    pct = pnl_report.max_fe_spot_cache_session_pct_move(
        session_start.isoformat(),
        log_path=log_file,
        cache_path=cache_file,
    )
    assert pct == pytest.approx(0.1912, rel=1e-3)


def test_compute_mark_delta_est_when_spot_cache_moved(tmp_path: Path) -> None:
    session_start = datetime(2026, 5, 30, 0, 0, 0, tzinfo=timezone.utc)
    before_ts = int((session_start - timedelta(hours=12)).timestamp())
    after_ts = int((session_start + timedelta(hours=6)).timestamp())
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "\n".join(
            [
                f"=== CYCLE {before_ts}",
                "[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2500.0000 | json_floor=2500.0000 | effective_floor=2500.0000",
                "2026-05-29 12:00:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$132.00 | USDT=$10.00 | "
                "USDC=$20.00 | STABLE_USD=$30.00 | WMATIC=0.000000 | POL=0 | POL_USD=$0.00 | FE_USD=$102.00",
                f"=== CYCLE {after_ts}",
                "[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2022.0000 | json_floor=2500.0000 | effective_floor=2022.0000",
                "2026-05-31 12:00:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$122.00 | USDT=$10.00 | "
                "USDC=$20.00 | STABLE_USD=$30.00 | WMATIC=0.000000 | POL=0 | POL_USD=$0.00 | FE_USD=$92.00",
            ]
        ),
        encoding="utf-8",
    )
    cache_file = tmp_path / "fe_usd_spot_cache.json"
    cache_file.write_text(
        json.dumps({"WETH_ALPHA": {"spot_usd": 2022.0, "updated_unix": float(after_ts)}}),
        encoding="utf-8",
    )
    delta = pnl_report.compute_mark_delta_est(
        session_start.isoformat(),
        current_fe_usd=92.0,
        log_path=log_file,
        cache_path=cache_file,
    )
    assert delta == pytest.approx(-10.0)


def test_format_mark_delta_est_line_hidden_when_spot_stable(tmp_path: Path) -> None:
    session_start = datetime(2026, 5, 30, 0, 0, 0, tzinfo=timezone.utc)
    ts = int((session_start - timedelta(hours=1)).timestamp())
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        f"=== CYCLE {ts}\n"
        "[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2000.0000 | json_floor=2000.0000 | effective_floor=2000.0000\n",
        encoding="utf-8",
    )
    cache_file = tmp_path / "fe_usd_spot_cache.json"
    cache_file.write_text(
        json.dumps({"WETH_ALPHA": {"spot_usd": 2010.0, "updated_unix": float(ts)}}),
        encoding="utf-8",
    )
    assert (
        pnl_report.format_mark_delta_est_line(
            session_start.isoformat(),
            log_path=log_file,
            cache_path=cache_file,
        )
        is None
    )


def test_format_mark_delta_est_line_contract(tmp_path: Path) -> None:
    session_start = datetime(2026, 5, 30, 0, 0, 0, tzinfo=timezone.utc)
    before_ts = int((session_start - timedelta(hours=12)).timestamp())
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "\n".join(
            [
                f"=== CYCLE {before_ts}",
                "[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2500.0000 | json_floor=2500.0000 | effective_floor=2500.0000",
                "2026-05-29 12:00:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$132.00 | USDT=$0 | "
                "USDC=$30.00 | STABLE_USD=$30.00 | WMATIC=0 | POL=0 | POL_USD=$0 | FE_USD=$102.00",
            ]
        ),
        encoding="utf-8",
    )
    cache_file = tmp_path / "fe_usd_spot_cache.json"
    cache_file.write_text(
        json.dumps({"WETH_ALPHA": {"spot_usd": 2022.0, "updated_unix": float(before_ts) + 3600}}),
        encoding="utf-8",
    )
    line = pnl_report.format_mark_delta_est_line(
        session_start.isoformat(),
        current_fe_usd=92.0,
        log_path=log_file,
        cache_path=cache_file,
    )
    assert line == "mark_delta_est: $-10.00 (FE spot cache)"


def _write_portfolio_history(
    tmp_path: Path,
    rows: list[tuple[str, float, float, float]],
) -> Path:
    """Write CSV with ``(timestamp, usdt, usdc, total_value)`` tuples."""
    csv_file = tmp_path / "portfolio_history.csv"
    lines = ["timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value"]
    for ts, usdt, usdc, total in rows:
        lines.append(f"{ts},{usdt:.6f},{usdc:.6f},0,0,0.1,{total:.6f}")
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_file


def test_detect_flow_events_deposit_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PNL_FLOW_STEP_MIN_USD", "5")
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            ("2026-05-30T08:00:00+00:00", 10.0, 20.0, 100.0),
            ("2026-05-30T10:00:00+00:00", 28.0, 20.0, 118.0),
        ],
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    events = pnl_report.detect_flow_events_heuristic(
        min_usd=5.0,
        lookback_hours=24.0,
        now_utc=now,
    )
    assert len(events) == 1
    assert events[0].kind == "deposit_est"
    assert events[0].amount_usd == pytest.approx(18.0)
    assert events[0].source == "heuristic"
    assert events[0].confidence == pytest.approx(1.0)


def test_detect_flow_events_flat_market_no_tag(tmp_path: Path, monkeypatch) -> None:
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            ("2026-05-30T08:00:00+00:00", 30.0, 30.0, 100.0),
            ("2026-05-30T10:00:00+00:00", 30.0, 30.0, 101.0),
            ("2026-05-30T12:00:00+00:00", 30.0, 30.0, 99.5),
        ],
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    now = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc)
    events = pnl_report.detect_flow_events_heuristic(
        min_usd=5.0,
        lookback_hours=24.0,
        now_utc=now,
    )
    assert events == []


def test_detect_flow_events_withdrawal_step(tmp_path: Path, monkeypatch) -> None:
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            ("2026-05-30T08:00:00+00:00", 40.0, 40.0, 120.0),
            ("2026-05-30T10:00:00+00:00", 25.0, 25.0, 90.0),
        ],
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    events = pnl_report.detect_flow_events_heuristic(
        min_usd=5.0,
        lookback_hours=24.0,
        now_utc=now,
    )
    assert len(events) == 1
    assert events[0].kind == "withdraw_est"
    assert events[0].amount_usd == pytest.approx(30.0)


def test_detect_flow_events_below_threshold_ignored(tmp_path: Path, monkeypatch) -> None:
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            ("2026-05-30T08:00:00+00:00", 10.0, 10.0, 100.0),
            ("2026-05-30T10:00:00+00:00", 13.0, 10.0, 103.0),
        ],
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    events = pnl_report.detect_flow_events_heuristic(
        min_usd=5.0,
        lookback_hours=24.0,
        now_utc=now,
    )
    assert events == []


def test_detect_flow_events_weth_rotation_not_deposit(tmp_path: Path, monkeypatch) -> None:
    """Stable down + equity mark up: TOTAL step not aligned with stables → no deposit tag."""
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            ("2026-05-30T08:00:00+00:00", 50.0, 50.0, 150.0),
            ("2026-05-30T10:00:00+00:00", 30.0, 30.0, 152.0),
        ],
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    events = pnl_report.detect_flow_events_heuristic(
        min_usd=5.0,
        lookback_hours=24.0,
        now_utc=now,
    )
    assert events == []


def test_load_manual_flow_events_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "pnl_flow_events.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"timestamp": "2026-05-31T12:00:00+00:00", "kind": "deposit", "amount_usd": 18.0}',
                "# comment",
                '{"ts": "2026-05-30T08:00:00+00:00", "kind": "withdraw", "amount_usd": 5.0}',
                "not json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    events = pnl_report.load_manual_flow_events(path)
    assert len(events) == 2
    assert events[0].kind == "withdraw"
    assert events[0].source == "manual"
    assert events[1].kind == "deposit"
    assert events[1].amount_usd == pytest.approx(18.0)


def test_compute_flow_adjusted_session_pnl_subtracts_deposits() -> None:
    events = [
        pnl_report.FlowEvent(
            ts=datetime(2026, 5, 31, 10, 0, 0, tzinfo=timezone.utc),
            kind="deposit_est",
            amount_usd=18.0,
            source="heuristic",
            confidence=1.0,
        )
    ]
    adjusted, pct = pnl_report.compute_flow_adjusted_session_pnl(20.0, 100.0, events)
    assert adjusted == pytest.approx(2.0)
    assert pct == pytest.approx(2.0)


def test_format_flow_adjusted_line_contract(tmp_path: Path, monkeypatch) -> None:
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            ("2026-05-30T08:00:00+00:00", 10.0, 20.0, 100.0),
            ("2026-05-30T10:00:00+00:00", 28.0, 20.0, 118.0),
        ],
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    monkeypatch.setenv("PNL_FLOW_TAG_ENABLED", "true")
    session_start = "2026-05-30T00:00:00+00:00"
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    line = pnl_report.format_flow_adjusted_line(
        19.8,
        100.0,
        session_start,
        now_utc=now,
    )
    assert line is not None
    assert line.startswith("Flow-adjusted session PnL: $+1.80 (+1.80%)")
    assert "detected flows: deposit +$18.00 @ 2026-05-30T10:00:00+00:00 (est)" in line


def test_format_flow_adjusted_line_disabled_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("PNL_FLOW_TAG_ENABLED", "false")
    line = pnl_report.format_flow_adjusted_line(
        10.0,
        100.0,
        "2026-05-30T00:00:00+00:00",
    )
    assert line is None


def test_print_daily_summary_includes_flow_adjusted_line(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            ("2026-05-05T00:00:00+00:00", 10.0, 75.0, 85.0),
            ("2026-05-06T09:00:00+00:00", 28.0, 75.0, 103.0),
        ],
    )
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(
        "2026-05-06 10:02:00 [nanoclaw] WALLET TOTAL USD | TOTAL=$103.80 | USDT=$28.00 | "
        "USDC=$75.00 | STABLE_USD=$103.00 | WMATIC=0.000000 | POL=0 | FE_USD=$0.80\n",
        encoding="utf-8",
    )
    session_file = tmp_path / "portfolio_session_baseline.json"
    session_file.write_text(
        json.dumps(
            {
                "session_start_total": 85.0,
                "session_started_at": "2026-05-05T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "LOG_FILE", str(log_file))
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    monkeypatch.setattr(pnl_report, "SESSION_BASELINE_FILE", str(session_file))
    monkeypatch.setenv("PNL_FLOW_TAG_ENABLED", "true")
    monkeypatch.setenv("PNL_FLOW_STEP_MIN_USD", "5")

    fixed_now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fixed_now

        @staticmethod
        def fromisoformat(raw):
            text = str(raw or "").strip()
            return datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)

    monkeypatch.setattr(pnl_report, "datetime", _FakeDateTime)
    monkeypatch.setattr(pnl_report, "resolve_portfolio_baseline_usd", lambda total: 100.0)

    pnl_report.print_daily_summary(lookback="24h")
    out = capsys.readouterr().out
    assert "Flow-adjusted session PnL:" in out
    assert "detected flows:" in out
