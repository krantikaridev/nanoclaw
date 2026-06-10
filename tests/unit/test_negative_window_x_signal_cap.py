"""Tests for X-SIGNAL max trade cap when 12h window is negative."""

from __future__ import annotations

import pytest

from nanoclaw.negative_window_x_signal_cap import resolve_effective_max_trade_usd


def test_cap_applies_when_window_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanoclaw.negative_window_x_signal_cap._enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoclaw.negative_window_x_signal_cap.resolve_window_pnl_pct",
        lambda **kw: -1.5,
    )
    monkeypatch.setattr(
        "nanoclaw.negative_window_x_signal_cap._max_trade_usd",
        lambda: 10.0,
    )
    assert resolve_effective_max_trade_usd(28.0) == pytest.approx(10.0)


def test_no_cap_when_window_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanoclaw.negative_window_x_signal_cap._enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoclaw.negative_window_x_signal_cap.resolve_window_pnl_pct",
        lambda **kw: 0.5,
    )
    assert resolve_effective_max_trade_usd(28.0) == pytest.approx(28.0)


def test_inactive_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanoclaw.negative_window_x_signal_cap._enabled",
        lambda: False,
    )
    assert resolve_effective_max_trade_usd(28.0, window_pct=-3.0) == pytest.approx(28.0)
