"""Tests for external_layer auto_pause integration."""

from __future__ import annotations

import pytest

from external_layer.auto_pause import apply_auto_pause_control, evaluate_auto_pause
from external_layer.unpause_hysteresis import (
    format_hysteresis_log,
    hysteresis_window_floor_pct,
    reset_unpause_hysteresis_for_tests,
    unpause_hysteresis_streak,
)


class _GreenPass:
    overall_pass = True
    readiness_pass = True
    session_pass = True
    window_pass = True
    pause_pass = True
    rotation_open = ()

    def trading_allowed(self) -> bool:
        return True


def test_apply_auto_pause_disabled_passthrough(monkeypatch) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_PAUSE_ENABLED", "false")
    payload = {"paused": True, "reason": "manual"}
    out = apply_auto_pause_control(payload)
    assert out == payload


def test_apply_auto_pause_enabled_sets_paused_from_gate(monkeypatch) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_PAUSE_ENABLED", "true")

    class _FakeResult:
        overall_pass = True
        readiness_pass = True
        rotation_open = ("WETH_ALPHA",)

        def trading_allowed(self) -> bool:
            return True

    monkeypatch.setattr(
        "external_layer.auto_pause.evaluate_auto_pause",
        lambda: (True, "auto_unpause | test", ("WETH_ALPHA",)),
    )
    out = apply_auto_pause_control({"paused": True, "max_copy_trade_pct": 0.02})
    assert out["paused"] is False
    assert out["auto_pause_control"] is True
    assert out["rotation_open"] == ["WETH_ALPHA"]


@pytest.fixture(autouse=True)
def _reset_hysteresis() -> None:
    reset_unpause_hysteresis_for_tests()


def test_unpause_hysteresis_single_tick_above_floor_does_not_unpause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED", "true")
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS", "6")
    monkeypatch.setenv("EXTERNAL_AUTO_WINDOW_MIN_PCT", "-2.0")
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_WINDOW_BUFFER_PCT", "0.25")

    monkeypatch.setattr(
        "scripts.nano_green.evaluate_green_gate",
        lambda *a, **k: _GreenPass(),
    )
    # Above -2% floor (green passes) but below -1.75% hysteresis floor — no streak credit.
    monkeypatch.setattr(
        "external_layer.unpause_hysteresis.resolve_window_pnl_pct",
        lambda *a, **k: -1.9,
    )

    allowed, reason, _ = evaluate_auto_pause()
    assert allowed is False
    assert "unpause hysteresis" in reason
    assert unpause_hysteresis_streak() == 0


def test_unpause_hysteresis_requires_consecutive_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED", "true")
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS", "3")
    monkeypatch.setenv("EXTERNAL_AUTO_WINDOW_MIN_PCT", "-2.0")
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_WINDOW_BUFFER_PCT", "0.25")

    monkeypatch.setattr(
        "scripts.nano_green.evaluate_green_gate",
        lambda *a, **k: _GreenPass(),
    )
    monkeypatch.setattr(
        "external_layer.unpause_hysteresis.resolve_window_pnl_pct",
        lambda *a, **k: -1.5,
    )

    for tick in range(1, 3):
        allowed, reason, _ = evaluate_auto_pause()
        assert allowed is False, f"tick {tick}"
        assert "unpause hysteresis" in reason
        assert unpause_hysteresis_streak() == tick

    allowed, reason, _ = evaluate_auto_pause()
    assert allowed is True
    assert reason.startswith("auto_unpause |")
    assert unpause_hysteresis_streak() == 3


def test_unpause_hysteresis_log_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED", "true")
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS", "6")
    from external_layer.unpause_hysteresis import record_unpause_hysteresis_tick

    for _ in range(3):
        monkeypatch.setattr(
            "external_layer.unpause_hysteresis.resolve_window_pnl_pct",
            lambda *a, **k: -1.5,
        )
        record_unpause_hysteresis_tick(hours=12.0, window_min_pct=-2.0)
    line = format_hysteresis_log(-1.9)
    assert line == "[external] auto_unpause hysteresis | ticks=3/6 | window=-1.9%"


def test_hysteresis_window_floor_includes_buffer() -> None:
    assert hysteresis_window_floor_pct(-2.0) == pytest.approx(-1.75)


def test_unpause_hysteresis_disabled_allows_immediate_unpause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED", "false")
    monkeypatch.setattr(
        "scripts.nano_green.evaluate_green_gate",
        lambda *a, **k: _GreenPass(),
    )
    allowed, reason, _ = evaluate_auto_pause()
    assert allowed is True
    assert reason.startswith("auto_unpause |")
