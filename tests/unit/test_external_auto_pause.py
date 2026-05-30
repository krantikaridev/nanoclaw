"""Tests for external_layer auto_pause integration."""

from __future__ import annotations

from external_layer.auto_pause import apply_auto_pause_control


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
