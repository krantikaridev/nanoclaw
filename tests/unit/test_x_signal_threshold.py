"""Threshold helper used by followed_equities JSON + env."""

import clean_swap


def test_effective_floor_uses_strict_max(monkeypatch):
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_MIN_STRENGTH", 0.7)

    assert clean_swap._effective_equity_signal_min({"min_signal_strength": 0.5}) == 0.7


def test_effective_floor_uses_json_when_higher(monkeypatch):
    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_MIN_STRENGTH", 0.60)

    assert clean_swap._effective_equity_signal_min({"min_signal_strength": 0.72}) == 0.72
