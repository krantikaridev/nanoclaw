"""Unit tests for external_layer.opex_gate."""

from __future__ import annotations

import pytest

from external_layer import opex_gate as og


def test_opex_gate_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    og.reset_opex_gate_state_for_tests()
    monkeypatch.setenv("OPEX_RUNWAY_AUTO_CHECK_ENABLED", "false")
    og.maybe_run_opex_runway_check(stable_usd=100.0, now_unix=1_000_000.0)
    assert og._last_check_unix == 0.0


def test_opex_gate_runs_on_interval(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    og.reset_opex_gate_state_for_tests()
    monkeypatch.setenv("OPEX_RUNWAY_AUTO_CHECK_ENABLED", "true")
    monkeypatch.setenv("OPEX_MONTHLY_USD", "10")
    monkeypatch.setenv("OPEX_RUNWAY_ALERT_DAYS", "14")
    og.maybe_run_opex_runway_check(stable_usd=14.57, now_unix=1_000_000.0)
    out = capsys.readouterr().out
    assert "opex_runway OK" in out
    assert og._last_check_unix == pytest.approx(1_000_000.0)


def test_opex_gate_throttles_repeat_ok(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    og.reset_opex_gate_state_for_tests()
    monkeypatch.setenv("OPEX_RUNWAY_AUTO_CHECK_ENABLED", "true")
    monkeypatch.setenv("OPEX_MONTHLY_USD", "10")
    og.maybe_run_opex_runway_check(stable_usd=14.57, now_unix=1_000_000.0)
    capsys.readouterr()
    og.maybe_run_opex_runway_check(stable_usd=14.57, now_unix=1_000_100.0)
    out = capsys.readouterr().out
    assert out == ""
