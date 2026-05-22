"""Signal-Driven Rotation (May 2026): rotation priority vs strong buy, quality filter."""

from __future__ import annotations

import clean_swap
from modules import signal as signal_module
from nanoclaw.strategies.signal_equity_trader import FollowedEquity, SignalEquityTrader


def _asset(symbol: str, strength: float, *, upside: float = 15.0) -> FollowedEquity:
    return FollowedEquity(
        symbol=symbol,
        token_address="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
        signal_strength=strength,
        upside_pct=upside,
    )


def _patch_trader(monkeypatch, assets: list[FollowedEquity]) -> None:
    class _T:
        def load_followed_equities(self):
            return assets

    monkeypatch.setattr(clean_swap, "X_SIGNAL_EQUITY_TRADER", _T())
    monkeypatch.setattr(clean_swap, "_load_followed_equities_json_dict", lambda: {"enabled": True, "min_signal_strength": 0.60})


def test_strong_buy_unchanged_below_strong_bar(monkeypatch):
    _patch_trader(monkeypatch, [_asset("LINK", 0.79)])
    monkeypatch.setattr(clean_swap, "X_SIGNAL_STRONG_THRESHOLD", 0.80)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_ROTATION_PRIORITY_THRESHOLD", 0.78)
    assert clean_swap._strong_x_signal_buy_present() is False


def test_rotation_priority_true_when_below_strong_but_above_rotation_bar(monkeypatch):
    _patch_trader(monkeypatch, [_asset("LINK", 0.79)])
    monkeypatch.setattr(clean_swap, "X_SIGNAL_STRONG_THRESHOLD", 0.80)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_ROTATION_PRIORITY_THRESHOLD", 0.78)
    assert clean_swap._rotation_priority_buy_present() is True
    assert clean_swap._strong_x_signal_buy_present() is False


def test_rotation_priority_defaults_match_strong_bar(monkeypatch):
    _patch_trader(monkeypatch, [_asset("WETH", 0.81)])
    monkeypatch.setattr(clean_swap, "X_SIGNAL_STRONG_THRESHOLD", 0.80)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_ROTATION_PRIORITY_THRESHOLD", 0.80)
    assert clean_swap._rotation_priority_buy_present() is True
    assert clean_swap._strong_x_signal_buy_present() is True


def test_rotation_priority_force_eligible_with_upside(monkeypatch):
    _patch_trader(monkeypatch, [_asset("LINK", 0.81, upside=18.0)])
    monkeypatch.setattr(clean_swap, "X_SIGNAL_STRONG_THRESHOLD", 0.85)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_ROTATION_PRIORITY_THRESHOLD", 0.85)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD", 0.80)
    monkeypatch.setattr(clean_swap, "X_SIGNAL_ROTATION_MIN_UPSIDE_PCT", 12.0)
    assert clean_swap._rotation_priority_buy_present() is True


def test_quality_filter_drops_weak_when_enabled(monkeypatch):
    monkeypatch.setattr(signal_module, "X_SIGNAL_MIN_ACTIONABLE_STRENGTH", 0.78)
    monkeypatch.setattr(signal_module, "X_SIGNAL_MIN_UPSIDE_PCT_FOR_WEAK", 0.0)
    fe = 0.80
    eligible = [_asset("NOISE", 0.72), _asset("OK", 0.82)]
    out = signal_module._filter_x_signal_quality_noise(eligible, force_eligible_threshold=fe)
    assert [a.symbol for a in out] == ["OK"]


def test_x_signal_dynamic_lo_hi_caps_when_usdc_low(monkeypatch):
    from nanoclaw.strategies import signal_equity_trader as set_mod

    def _fake_env_float(key: str, default: float = 0.0) -> float:
        return {
            "X_SIGNAL_DYNAMIC_TIER_HIGH_MIN": 0.90,
            "X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH": 20.0,
            "X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE": 15.0,
            "X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE": 12.0,
        }.get(key, default)

    monkeypatch.setattr(set_mod.cfg, "env_float", _fake_env_float)
    lo, hi = SignalEquityTrader._x_signal_dynamic_lo_hi(10.0, 0.88)
    assert hi <= 12.0 + 1e-6
    assert lo >= 8.0
