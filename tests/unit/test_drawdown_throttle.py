"""Unit tests for nanoclaw.drawdown_throttle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nanoclaw import drawdown_throttle as dt
from modules import swap_executor as se
from scripts import pnl_report


def _write_portfolio_history(
    tmp_path: Path,
    rows: list[tuple[str, float]],
) -> Path:
    csv_file = tmp_path / "portfolio_history.csv"
    lines = ["timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value"]
    for ts, total in rows:
        lines.append(f"{ts},1.0,1.0,0,0,0.1,{total:.6f}")
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_file


def _patch_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dt.cfg, "DRAWDOWN_THROTTLE_ENABLED", True)
    monkeypatch.setattr(dt.cfg, "DRAWDOWN_THROTTLE_WINDOW_HOURS", 8.0)
    monkeypatch.setattr(dt.cfg, "DRAWDOWN_THROTTLE_TRIGGER_PCT", -1.0)
    monkeypatch.setattr(dt.cfg, "DRAWDOWN_THROTTLE_NOTIONAL_MULT", 0.5)


def test_window_pnl_matches_nano_green_math(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ref_ts = (now - timedelta(hours=8)).isoformat()
    csv_file = _write_portfolio_history(
        tmp_path,
        [
            (ref_ts, 100.0),
            ("2026-06-01T11:30:00+00:00", 99.0),
        ],
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    monkeypatch.setattr(
        pnl_report,
        "get_current_balance",
        lambda: {"total": 98.8},
    )

    pct = dt.resolve_window_pnl_pct(current_total=98.8, now_utc=now, history_path=csv_file)
    assert pct == pytest.approx(-1.2, abs=0.05)

    cutoff = now - timedelta(hours=8.0)
    ref, ref_ts_dt = pnl_report._resolve_history_at_or_before(cutoff)  # noqa: SLF001
    assert ref == pytest.approx(100.0)
    assert ref_ts_dt is not None
    ref_local, ref_ts_local = dt.resolve_history_at_or_before(cutoff, csv_path=csv_file)
    assert ref_local == ref
    assert ref_ts_local == ref_ts_dt
    manual_pct = (98.8 - float(ref)) / float(ref) * 100.0
    assert pct == pytest.approx(manual_pct)


def test_throttle_active_below_trigger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    state = dt.resolve_drawdown_throttle(window_pct=-1.2)
    assert state.active is True
    assert state.notional_mult == pytest.approx(0.5)


def test_throttle_inactive_above_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    state = dt.resolve_drawdown_throttle(window_pct=-0.5)
    assert state.active is False
    assert state.notional_mult == pytest.approx(1.0)


def test_apply_tiered_max_throttle_logs_and_halves(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_enabled(monkeypatch)
    throttled = dt.apply_tiered_max_throttle(10.0, window_pct=-1.2)
    assert throttled == pytest.approx(5.0)
    out = capsys.readouterr().out
    assert "[nanoclaw] DRAWDOWN THROTTLE | window=-1.2% | tiered_max=$5.00" in out


def test_apply_buy_size_multiplier_halves_positive_mult(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    assert dt.apply_buy_size_multiplier(0.4, window_pct=-1.5) == pytest.approx(0.2)
    assert dt.apply_buy_size_multiplier(0.0, window_pct=-1.5) == pytest.approx(0.0)


def test_disabled_returns_unchanged(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(dt.cfg, "DRAWDOWN_THROTTLE_ENABLED", False)
    assert dt.apply_tiered_max_throttle(10.0, window_pct=-2.0) == pytest.approx(10.0)
    assert dt.apply_buy_size_multiplier(0.8, window_pct=-2.0) == pytest.approx(0.8)
    assert capsys.readouterr().out == ""


class _Bal:
    def __init__(
        self,
        *,
        usdt: float = 0.0,
        usdc: float = 0.0,
        total: float = 140.0,
        fe: float = 111.0,
        wmatic: float = 0.0,
    ) -> None:
        self.usdt = usdt
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = fe
        self.wmatic = wmatic
        self.pol = 14.0


def test_tiered_cap_halved_under_drawdown(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_enabled(monkeypatch)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL", 0.85)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 132.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)

    bal = _Bal(usdt=0.93, usdc=26.53, total=140.0, fe=111.0)
    monkeypatch.setattr(dt, "resolve_window_pnl_pct", lambda **kwargs: -1.2)
    capped = se.fe_stable_runway_tiered_cap_notional_usd(
        bal,
        signal_strength=0.87,
        proposed_notional_usd=12.0,
    )
    assert capped == pytest.approx(5.0)
