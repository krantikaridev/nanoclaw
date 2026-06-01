"""Unit tests for nanoclaw.adverse_churn_guard (P9 adverse churn guard)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nanoclaw import adverse_churn_guard as guard
from nanoclaw import pnl_adverse_day as adverse


def _metrics(
    *,
    is_adverse: bool = True,
    fill_count: int = 4,
    total_delta_usd: float = -5.0,
) -> adverse.AdverseDayMetrics:
    return adverse.AdverseDayMetrics(
        window_hours=24.0,
        total_delta_usd=total_delta_usd,
        mark_delta_usd=-2.0,
        turnover_usd=30.0,
        fill_count=fill_count,
        gas_est_usd=0.2,
        realized_trade_est_usd=-2.83,
        churn_cost_est_usd=0.23,
        is_adverse=is_adverse,
        ref_total_usd=100.0,
        current_total_usd=95.0,
    )


def _guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADVERSE_CHURN_GUARD_ENABLED", "true")
    monkeypatch.setenv("ADVERSE_CHURN_GUARD_FILL_MULT", "0.5")
    monkeypatch.setenv("PNL_ADVERSE_DAY_MIN_FILLS", "3")


def test_disabled_is_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ADVERSE_CHURN_GUARD_ENABLED", "false")
    flag_path = tmp_path / "adverse_churn_flag.json"
    assert guard.evaluate_and_persist(_metrics(), flag_path=flag_path, log_fn=list.append) is False
    assert not flag_path.is_file()


def test_not_adverse_writes_inactive_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _guard_env(monkeypatch)
    flag_path = tmp_path / "adverse_churn_flag.json"
    logs: list[str] = []
    active = guard.evaluate_and_persist(
        _metrics(is_adverse=False, fill_count=10),
        flag_path=flag_path,
        log_fn=logs.append,
    )
    assert active is False
    assert logs == []
    payload = json.loads(flag_path.read_text(encoding="utf-8"))
    assert payload["active"] is False
    assert payload["recommended_notional_mult"] == 0.5


def test_adverse_low_fills_inactive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _guard_env(monkeypatch)
    flag_path = tmp_path / "adverse_churn_flag.json"
    logs: list[str] = []
    active = guard.evaluate_and_persist(
        _metrics(fill_count=2),
        flag_path=flag_path,
        log_fn=logs.append,
    )
    assert active is False
    assert logs == []
    payload = json.loads(flag_path.read_text(encoding="utf-8"))
    assert payload["active"] is False


def test_adverse_meets_min_fills_logs_and_sets_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _guard_env(monkeypatch)
    flag_path = tmp_path / "adverse_churn_flag.json"
    logs: list[str] = []
    metrics = _metrics(fill_count=4, total_delta_usd=-8.5)
    active = guard.evaluate_and_persist(metrics, flag_path=flag_path, log_fn=logs.append)
    assert active is True
    assert len(logs) == 1
    assert "[nanoclaw] ADVERSE CHURN GUARD" in logs[0]
    assert "fills=4" in logs[0]
    assert "recommended_notional_mult=0.50" in logs[0]
    payload = json.loads(flag_path.read_text(encoding="utf-8"))
    assert payload["active"] is True
    assert payload["fill_count"] == 4
    assert payload["min_fills"] == 3
    assert payload["total_delta_usd"] == pytest.approx(-8.5)
    assert payload["recommended_notional_mult"] == 0.5


def test_read_recommended_notional_mult_v2_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _guard_env(monkeypatch)
    flag_path = tmp_path / "adverse_churn_flag.json"
    guard.evaluate_and_persist(_metrics(), flag_path=flag_path, log_fn=lambda _: None)
    assert guard.guard_active(flag_path) is True
    assert guard.read_recommended_notional_mult(path=flag_path) == 0.5
    assert guard.read_recommended_notional_mult(path=flag_path, default=1.0) == 0.5


def test_read_mult_default_when_inactive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _guard_env(monkeypatch)
    flag_path = tmp_path / "adverse_churn_flag.json"
    guard.evaluate_and_persist(
        _metrics(is_adverse=False),
        flag_path=flag_path,
        log_fn=lambda _: None,
    )
    assert guard.guard_active(flag_path) is False
    assert guard.read_recommended_notional_mult(path=flag_path, default=1.0) == 1.0


def test_build_flag_payload_timestamp() -> None:
    fixed = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    payload = guard.build_flag_payload(_metrics(), active=True, now_utc=fixed)
    assert payload["updated_at"] == "2026-06-01T12:00:00+00:00"


def test_pnl_report_oneliner_triggers_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import pnl_report

    _guard_env(monkeypatch)
    flag_path = tmp_path / "adverse_churn_flag.json"
    monkeypatch.setattr(guard, "ADVERSE_CHURN_FLAG_FILE", flag_path)
    fake = _metrics(fill_count=5)
    monkeypatch.setattr(adverse, "compute_adverse_day_metrics", lambda **kwargs: fake)
    pnl_report._print_adverse_day_oneliner(95.0)
    out = capsys.readouterr().out
    assert "Adverse window:" in out
    assert "[nanoclaw] ADVERSE CHURN GUARD" in out
    payload = json.loads(flag_path.read_text(encoding="utf-8"))
    assert payload["active"] is True
