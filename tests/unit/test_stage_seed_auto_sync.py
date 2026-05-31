"""STAGE_SEED auto-sync from portfolio_history EMA."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import config as cfg
from nanoclaw import stage_seed as ss
from modules import swap_executor as se


class _Bal:
    def __init__(self, *, total: float = 122.0, usdc: float = 20.0) -> None:
        self.usdt = 0.0
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = 100.0
        self.wmatic = 0.0
        self.pol = 0.0


def _write_history_csv(path: Path, daily_totals: list[tuple[str, float]]) -> None:
    lines = ["timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value"]
    for day_iso, total in daily_totals:
        lines.append(f"{day_iso}T12:00:00+00:00,5.0,5.0,0,0,0.25,{total:.2f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_compute_ema_single_value() -> None:
    assert ss.compute_ema([150.0], 7) == pytest.approx(150.0)


def test_compute_ema_smoothing() -> None:
    values = [100.0, 110.0, 120.0, 130.0]
    ema = ss.compute_ema(values, 7)
    assert ema is not None
    assert 100.0 < ema < 130.0


def test_daily_close_series_uses_last_snapshot_per_day() -> None:
    ts1 = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 1, 22, 0, tzinfo=timezone.utc)
    ts3 = datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc)
    daily = ss.daily_close_series([(ts1, 100.0), (ts2, 105.0), (ts3, 110.0)])
    assert daily == [(ts1.date(), 105.0), (ts3.date(), 110.0)]


def test_portfolio_total_ema_from_csv(tmp_path: Path) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = [
        ((base + timedelta(days=i)).date().isoformat(), 100.0 + i * 10.0)
        for i in range(7)
    ]
    csv_path = tmp_path / "portfolio_history.csv"
    _write_history_csv(csv_path, rows)
    ema = ss.compute_portfolio_total_ema(ema_days=7, csv_path=csv_path)
    assert ema is not None
    assert ema >= 130.0


def test_resolve_seed_auto_sync_disabled_uses_explicit() -> None:
    seed = ss.resolve_operating_reserve_seed_usd(
        90.0,
        explicit_seed_usd=132.0,
        auto_sync_enabled=False,
    )
    assert seed == pytest.approx(132.0)


def test_resolve_seed_auto_sync_max_env_and_ema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = [
        ((base + timedelta(days=i)).date().isoformat(), 170.0)
        for i in range(7)
    ]
    csv_path = tmp_path / "portfolio_history.csv"
    _write_history_csv(csv_path, rows)
    log_state = tmp_path / "ema_log.json"

    seed = ss.resolve_operating_reserve_seed_usd(
        120.0,
        explicit_seed_usd=158.0,
        auto_sync_enabled=True,
        ema_days=7,
        min_usd=50.0,
        csv_path=csv_path,
        log_state_path=log_state,
    )
    assert seed == pytest.approx(170.0)


def test_resolve_seed_auto_sync_env_floor_when_ema_lower(tmp_path: Path) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = [
        ((base + timedelta(days=i)).date().isoformat(), 140.0)
        for i in range(7)
    ]
    csv_path = tmp_path / "portfolio_history.csv"
    _write_history_csv(csv_path, rows)
    log_state = tmp_path / "ema_log.json"

    seed = ss.resolve_operating_reserve_seed_usd(
        120.0,
        explicit_seed_usd=158.0,
        auto_sync_enabled=True,
        ema_days=7,
        min_usd=50.0,
        csv_path=csv_path,
        log_state_path=log_state,
    )
    assert seed == pytest.approx(158.0)


def test_stage_seed_ema_logs_once_per_day(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = tmp_path / "ema_log.json"
    now = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)
    assert ss.maybe_log_stage_seed_ema_once_daily(
        seed_usd=158.0,
        reserve_floor_usd=15.8,
        now_utc=now,
        state_path=state,
    )
    out1 = capsys.readouterr().out
    assert "STAGE_SEED_EMA" in out1
    assert "seed_usd=158.00" in out1
    assert "reserve_floor=15.80" in out1

    assert not ss.maybe_log_stage_seed_ema_once_daily(
        seed_usd=158.0,
        reserve_floor_usd=15.8,
        now_utc=now + timedelta(hours=6),
        state_path=state,
    )
    assert capsys.readouterr().out == ""


def test_operating_reserve_uses_auto_sync_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = [
        ((base + timedelta(days=i)).date().isoformat(), 200.0)
        for i in range(7)
    ]
    csv_path = tmp_path / "portfolio_history.csv"
    _write_history_csv(csv_path, rows)
    monkeypatch.setattr(cfg, "STAGE_SEED_AUTO_SYNC_ENABLED", True)
    monkeypatch.setattr(cfg, "STAGE_SEED_USD", 158.0)
    monkeypatch.setattr(cfg, "STAGE_SEED_AUTO_SYNC_EMA_DAYS", 7)
    monkeypatch.setattr(cfg, "STAGE_SEED_AUTO_SYNC_MIN_USD", 50.0)
    monkeypatch.setattr(cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(ss, "PORTFOLIO_HISTORY_FILE", str(csv_path))
    monkeypatch.setattr(
        ss,
        "_STAGE_SEED_EMA_LOG_STATE",
        tmp_path / "ema_log.json",
    )

    bal = _Bal(usdc=15.0, total=195.0)
    ctx = se._operating_reserve_buy_block_context(bal)  # noqa: SLF001
    assert ctx is not None
    assert ctx["seed_usd"] == pytest.approx(200.0)
    assert ctx["reserve_floor_usd"] == pytest.approx(20.0)
