"""Tests for dual-window auto_unpause gate (8h AND 12h PASS)."""

from __future__ import annotations

from pathlib import Path

import pytest

from external_layer.auto_pause import evaluate_auto_pause
from external_layer.dual_window_unpause import evaluate_dual_window_unpause
from external_layer.unpause_hysteresis import reset_unpause_hysteresis_for_tests


class _GreenPass:
    overall_pass = True
    readiness_pass = True
    session_pass = True
    window_pass = True
    pause_pass = True
    rotation_open = ()

    def trading_allowed(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _reset_hysteresis() -> None:
    reset_unpause_hysteresis_for_tests()


def test_dual_window_blocks_when_short_window_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW", "true")
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED", "false")

    def _window_check(root, *, hours, window_min_pct, current_total):
        if float(hours) == 8.0:
            return False, "FAIL | 8h window PnL -4.0% floor=-2.0%"
        return True, "PASS | 12h window PnL +0.5% floor=-2.0%"

    monkeypatch.setattr("scripts.nano_green.evaluate_green_gate", lambda *a, **k: _GreenPass())
    monkeypatch.setattr("scripts.nano_green._session_pnl_check", lambda *a, **k: (True, "", 0.0, 135.0))
    monkeypatch.setattr("scripts.nano_green._window_pnl_check", _window_check)

    allowed, reason, _ = evaluate_auto_pause()
    assert allowed is False
    assert "dual-window unpause blocked" in reason
    assert "8h" in reason


def test_dual_window_allows_when_both_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW", "true")
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED", "false")

    def _window_check(root, *, hours, window_min_pct, current_total):
        return True, f"PASS | {hours:.0f}h window PnL +0.5%"

    monkeypatch.setattr("scripts.nano_green.evaluate_green_gate", lambda *a, **k: _GreenPass())
    monkeypatch.setattr("scripts.nano_green._session_pnl_check", lambda *a, **k: (True, "", 0.0, 135.0))
    monkeypatch.setattr("scripts.nano_green._window_pnl_check", _window_check)

    allowed, reason, _ = evaluate_auto_pause()
    assert allowed is True
    assert reason.startswith("auto_unpause |")
    assert "8h PASS" in reason
    assert "12h PASS" in reason


def test_evaluate_dual_window_rejects_skip_as_not_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "scripts.nano_green._session_pnl_check",
        lambda *a, **k: (True, "", 0.0, 100.0),
    )

    def _window_check(root, *, hours, window_min_pct, current_total):
        if float(hours) == 8.0:
            return True, "SKIP | no portfolio_history row"
        return True, "PASS | 12h window PnL +0.5%"

    monkeypatch.setattr("scripts.nano_green._window_pnl_check", _window_check)
    ok, detail = evaluate_dual_window_unpause(tmp_path, window_min_pct=-2.0, long_hours=12.0)
    assert ok is False
    assert "8h" in detail
