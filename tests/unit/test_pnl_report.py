"""Unit tests for scripts.pnl_report snapshot extraction."""

from __future__ import annotations

from pathlib import Path

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
