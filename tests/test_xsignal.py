"""Defaults for X-Signal dynamic sizing config."""

import importlib

import pytest


_X_SIGNAL_ENV_KEYS = (
    "X_SIGNAL_DYNAMIC_TIER_HIGH_MIN",
    "X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH",
    "X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE",
    "X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE",
)


def test_dynamic_trade_size_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _X_SIGNAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    import nanoclaw.config as cfg

    importlib.reload(cfg)
    assert cfg.X_SIGNAL.USDC_GTE_TIER_HIGH == 20.0
    assert cfg.X_SIGNAL.USDC_BELOW_FORCE_ELIGIBLE == 12.0
