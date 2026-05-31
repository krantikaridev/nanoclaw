"""Unit tests for nanoclaw.pnl_adverse_day (P3 adverse-window metrics)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nanoclaw import pnl_adverse_day as adverse
from scripts import pnl_report


def _write_log(tmp_path: Path, body: str) -> Path:
    log_file = tmp_path / "real_cron.log"
    log_file.write_text(body, encoding="utf-8")
    return log_file


def _write_history(tmp_path: Path, rows: list[tuple[str, float, float, float]]) -> Path:
    """rows: (iso_ts, usdt, usdc, total_value)."""
    csv_path = tmp_path / "portfolio_history.csv"
    lines = ["timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value"]
    for ts, usdt, usdc, total in rows:
        lines.append(f"{ts},{usdt},{usdc},0,0,0.1,{total}")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path


def _wallet_total_line(cycle_ts: int, total: float, fe_usd: float) -> str:
    return (
        f"[nanoclaw] === CYCLE {cycle_ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===\n"
        f"[nanoclaw] WALLET TOTAL USD | TOTAL=${total:.2f} | USDT=$1.00 | USDC=$1.00 | "
        f"STABLE_USD=$2.00 | WMATIC=0 | POL=0 | FE_USD=${fe_usd:.2f}"
    )


def _exec_success_line(cycle_ts: int) -> str:
    return (
        f"[nanoclaw] === CYCLE {cycle_ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===\n"
        "[nanoclaw] X-SIGNAL STF | EXEC SUCCESS | sym=WETH_ALPHA | tx=0xabc"
    )


def _attribution_line(cycle_ts: int, tx: str, sz: float) -> str:
    return (
        f"[nanoclaw] === CYCLE {cycle_ts} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===\n"
        f"[nanoclaw] TRADE_ATTRIBUTION tx={tx} dir=USDC→WMATIC sz≈{sz:.2f} msg=ok"
    )


@pytest.fixture(autouse=True)
def _default_adverse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PNL_ADVERSE_DAY_ENABLED", "true")
    monkeypatch.setenv("PNL_ADVERSE_DAY_WINDOW_HOURS", "24")
    monkeypatch.setenv("PNL_ADVERSE_DAY_MIN_FILLS", "3")
    monkeypatch.setenv("GAS_USD_EST_PER_FILL", "0.05")
    monkeypatch.setattr(
        pnl_report,
        "compute_authoritative_total_in_process",
        lambda: None,
    )


def test_count_exec_success_fills_window(tmp_path: Path) -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    inside = int((since + timedelta(hours=1)).timestamp())
    outside = int((now + timedelta(minutes=5)).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                _exec_success_line(inside),
                _exec_success_line(inside + 60),
                _exec_success_line(outside),
            ]
        ),
    )
    assert adverse.count_exec_success_fills(log_file, since_utc=since, until_utc=now) == 2


def test_adverse_metrics_high_churn_flat_mark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10 fills / ~$106 turnover, flat FE mark — loss attributed to churn/trade est."""
    now = datetime(2026, 5, 31, 18, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    start_ts = (since + timedelta(hours=2)).isoformat()
    mid_ts = (since + timedelta(hours=12)).isoformat()
    hist = _write_history(
        tmp_path,
        [
            (start_ts, 50.0, 50.0, 130.0),
            (mid_ts, 50.0, 50.0, 130.0),
        ],
    )
    lines: list[str] = []
    fe = 20.0
    for i in range(10):
        ts = int((since + timedelta(hours=3 + i * 0.5)).timestamp())
        lines.append(_exec_success_line(ts))
        lines.append(_attribution_line(ts, f"0x{i:040x}", 10.6))
        lines.append(_wallet_total_line(ts, 130.0 - (i + 1) * 0.05, fe))
    log_file = _write_log(tmp_path, "\n".join(lines))

    metrics = adverse.compute_adverse_day_metrics(
        current_total_usd=129.0,
        window_hours=24.0,
        log_path=log_file,
        portfolio_history_path=hist,
        now_utc=now,
    )

    assert metrics.is_adverse is True
    assert metrics.fill_count == 10
    assert metrics.turnover_usd == pytest.approx(106.0, rel=0.01)
    assert metrics.mark_delta_usd == pytest.approx(0.0, abs=0.01)
    assert metrics.gas_est_usd == pytest.approx(0.50)
    assert metrics.churn_cost_est_usd == pytest.approx(0.50 + 106.0 * 0.001)
    assert metrics.realized_trade_est_usd == pytest.approx(
        metrics.total_delta_usd - metrics.mark_delta_usd + metrics.churn_cost_est_usd
    )


def test_adverse_metrics_dump_mark_low_fills(tmp_path: Path) -> None:
    """FE mark drop explains loss; few fills — mark_delta dominates."""
    now = datetime(2026, 5, 31, 20, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    start_ts = since.isoformat()
    hist = _write_history(
        tmp_path,
        [(start_ts, 40.0, 40.0, 132.0)],
    )
    t0 = int((since + timedelta(hours=1)).timestamp())
    t1 = int((since + timedelta(hours=10)).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join(
            [
                _wallet_total_line(t0, 132.0, 30.0),
                _wallet_total_line(t1, 122.0, 20.0),
            ]
        ),
    )

    metrics = adverse.compute_adverse_day_metrics(
        current_total_usd=122.0,
        window_hours=24.0,
        log_path=log_file,
        portfolio_history_path=hist,
        now_utc=now,
    )

    assert metrics.is_adverse is True
    assert metrics.total_delta_usd == pytest.approx(-10.0)
    assert metrics.mark_delta_usd == pytest.approx(-10.0)
    assert metrics.fill_count == 0
    assert metrics.gas_est_usd == pytest.approx(0.0)


def test_oneliner_suppressed_below_min_fills(tmp_path: Path) -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    hist = _write_history(tmp_path, [(since.isoformat(), 10.0, 10.0, 100.0)])
    t0 = int((since + timedelta(hours=2)).timestamp())
    log_file = _write_log(
        tmp_path,
        "\n".join([_exec_success_line(t0), _wallet_total_line(t0, 99.0, 5.0)]),
    )
    metrics = adverse.compute_adverse_day_metrics(
        current_total_usd=99.0,
        window_hours=24.0,
        log_path=log_file,
        portfolio_history_path=hist,
        now_utc=now,
    )
    assert metrics.is_adverse is True
    assert metrics.fill_count == 1
    assert adverse.format_adverse_day_oneliner(metrics) is None


def test_oneliner_when_red_and_enough_fills(tmp_path: Path) -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    hist = _write_history(tmp_path, [(since.isoformat(), 10.0, 10.0, 100.0)])
    lines = []
    for i in range(3):
        ts = int((since + timedelta(hours=2 + i)).timestamp())
        lines.append(_exec_success_line(ts))
    log_file = _write_log(tmp_path, "\n".join(lines))
    metrics = adverse.compute_adverse_day_metrics(
        current_total_usd=95.0,
        window_hours=24.0,
        log_path=log_file,
        portfolio_history_path=hist,
        now_utc=now,
    )
    line = adverse.format_adverse_day_oneliner(metrics)
    assert line is not None
    assert "Adverse window: mark" in line
    assert "fills 3" in line


def test_not_adverse_when_total_up(tmp_path: Path) -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    since = now - timedelta(hours=24)
    hist = _write_history(tmp_path, [(since.isoformat(), 10.0, 10.0, 90.0)])
    metrics = adverse.compute_adverse_day_metrics(
        current_total_usd=100.0,
        window_hours=24.0,
        log_path=_write_log(tmp_path, ""),
        portfolio_history_path=hist,
        now_utc=now,
    )
    assert metrics.is_adverse is False
    detail = adverse.format_adverse_day_detail_lines(metrics)
    assert "n/a" in detail[0]


def test_build_report_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PNL_ADVERSE_DAY_ENABLED", "false")
    _metrics, lines = adverse.build_adverse_day_report(current_total_usd=100.0)
    assert _metrics is None
    assert "disabled" in lines[0].lower()


def test_pnl_report_print_adverse_oneliner(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = adverse.AdverseDayMetrics(
        window_hours=24.0,
        total_delta_usd=-5.0,
        mark_delta_usd=-2.0,
        turnover_usd=30.0,
        fill_count=4,
        gas_est_usd=0.2,
        realized_trade_est_usd=-2.83,
        churn_cost_est_usd=0.23,
        is_adverse=True,
        ref_total_usd=100.0,
        current_total_usd=95.0,
    )
    monkeypatch.setattr(adverse, "compute_adverse_day_metrics", lambda **kwargs: fake)
    pnl_report._print_adverse_day_oneliner(95.0)
    out = capsys.readouterr().out
    assert "Adverse window: mark $-2.00" in out
    assert "fills 4" in out
