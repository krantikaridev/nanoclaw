"""Unit tests for ``external_layer.clamp_policy`` env loading."""

from __future__ import annotations

import pytest

from external_layer import clamp_policy


@pytest.fixture(autouse=True)
def _reset_policy_cache(monkeypatch):
    monkeypatch.delenv("EXTERNAL_CLAMP_STREAK_EVALS", raising=False)
    monkeypatch.delenv("EXTERNAL_CLAMP_DURATION_SEC", raising=False)
    monkeypatch.delenv("EXTERNAL_RISK_TRAVEL_STABLE_USD", raising=False)
    clamp_policy.reload_risk_policy_for_tests()
    yield
    clamp_policy.reload_risk_policy_for_tests()


def test_load_risk_policy_defaults():
    p = clamp_policy.load_risk_policy()
    assert p.clamp.streak_evals == 3
    assert p.clamp.duration_sec == 600.0
    assert p.tier.travel_stable_usd == 95.0
    assert p.clamp.recovery_stable_usd == 95.0
    assert p.clamp.healthy_stable_usd == 100.0


def test_load_risk_policy_env_override(monkeypatch):
    monkeypatch.setenv("EXTERNAL_CLAMP_STREAK_EVALS", "4")
    monkeypatch.setenv("EXTERNAL_CLAMP_DURATION_SEC", "120")
    monkeypatch.setenv("EXTERNAL_RISK_TRAVEL_STABLE_USD", "90")
    p = clamp_policy.reload_risk_policy_for_tests()
    assert p.clamp.streak_evals == 4
    assert p.clamp.duration_sec == 120.0
    assert p.tier.travel_stable_usd == 90.0
    assert p.clamp.recovery_stable_usd == 90.0


def test_load_risk_policy_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("EXTERNAL_CLAMP_STREAK_EVALS", "not-a-number")
    p = clamp_policy.reload_risk_policy_for_tests()
    assert p.clamp.streak_evals == 3


def test_log_risk_policy_once_emits_single_line(capsys):
    clamp_policy.reload_risk_policy_for_tests()
    clamp_policy.log_risk_policy_once()
    clamp_policy.log_risk_policy_once()
    out = capsys.readouterr().out
    assert out.count("[EXTERNAL] risk_policy |") == 1
