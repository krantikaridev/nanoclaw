"""Unit tests for structured decision logging (learning/adaptation foundation)."""

from __future__ import annotations

import pytest

from modules import decision_log as dl


def test_log_decision_emits_parseable_fields(capsys):
    dl.log_decision(
        branch="X_SIGNAL",
        action="REJECT",
        reason="per_asset_cooldown",
        symbol="WETH_ALPHA",
        signal_strength=0.72,
        expected_edge_pct=1.2,
        notional_usd=11.5,
        wmatic_balance=42.5,
        extra="test=1",
    )
    captured = capsys.readouterr().out
    assert "DECISION |" in captured
    assert "branch=X_SIGNAL" in captured
    assert "action=REJECT" in captured
    assert "reason=per_asset_cooldown" in captured
    assert "symbol=WETH_ALPHA" in captured
    assert "signal=0.720" in captured
    assert "edge_pct=1.20" in captured
    assert "notional_usd=11.50" in captured
    assert "wmatic=42.500000" in captured
    assert "extra=test=1" in captured


def test_x_signal_counters_and_cycle_counters():
    state: dict = {}
    dl.log_x_signal_decision("A", "ACCEPT", "plan_selected", signal=0.9, state=state)
    dl.log_x_signal_decision("B", "REJECT", "gas_above_limit", signal=0.8, state=state)
    dl.record_x_signal_cycle_outcome(state, taken=True, reason="executable_plan", wmatic_balance=10.0)
    dl.record_x_signal_cycle_outcome(state, taken=False, reason="no_plan", wmatic_balance=10.0)

    root = state["decision_tracking"]["X_SIGNAL"]
    assert root["taken"] == 1
    assert root["skipped"] == 1
    assert root["cycle_taken"] == 1
    assert root["cycle_skipped"] == 1


def test_profit_take_success_rate():
    state: dict = {}
    dl.record_profit_take_execution(state, success=True, reason="swap_ok")
    dl.record_profit_take_execution(state, success=False, reason="swap_failed")

    rate = dl.profit_take_success_rate(state["decision_tracking"])
    assert rate == pytest.approx(0.5)
    summary = dl.format_tracking_summary(state)
    assert "DECISION_TRACKING |" in summary
    assert "profit_take_success_rate=50.0%" in summary


def test_log_tracking_summary_prints(capsys):
    state = {"decision_tracking": {"X_SIGNAL": {"taken": 2, "skipped": 5}}}
    dl.log_tracking_summary(state)
    captured = capsys.readouterr().out
    assert "DECISION_TRACKING |" in captured
    assert "x_signal_taken=2" in captured
