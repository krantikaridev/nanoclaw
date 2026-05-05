"""Unit tests for scripts.pnl_report snapshot extraction."""

from __future__ import annotations

from pathlib import Path

from scripts import pnl_report
from scripts.pnl_report import extract_snapshots


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
