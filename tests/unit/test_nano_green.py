"""Tests for scripts/nano_green.py — configurable window + session floor."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.nano_green import evaluate_green_gate, rotation_open_symbols


def _write_env(root: Path, **kwargs: str) -> None:
    (root / ".env").write_text(
        "\n".join(f"{k}={v}" for k, v in kwargs.items()) + "\n",
        encoding="utf-8",
    )


def _write_followed(root: Path, symbols: list[str]) -> None:
    assets = [{"symbol": s, "address": "0x" + "a" * 40, "decimals": 18} for s in symbols]
    (root / "followed_equities.json").write_text(
        json.dumps({"enabled": True, "assets": assets}),
        encoding="utf-8",
    )


def test_session_passes_at_minus_one_pct_floor(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_env(root, ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL="false", FE_STABLE_RUNWAY_ENABLED="true")
    _write_followed(root, ["WETH_ALPHA", "LINK_ALPHA"])
    (root / ".xsignal_blocked_symbols").write_text("LINK_ALPHA\n", encoding="utf-8")
    (root / "control.json").write_text(json.dumps({"paused": True}), encoding="utf-8")
    (root / "real_cron.log").write_text(
        "[CONTROL] paused=True → skipping new entry trades\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.nano_green.get_current_balance",
        lambda: {"total": 131.0, "source": "test"},
    )
    monkeypatch.setattr(
        "scripts.nano_green.resolve_session_baseline",
        lambda total, reset=False: (132.0, "2026-05-29T00:00:00Z"),
    )
    monkeypatch.setattr(
        "scripts.nano_green._fe_share_line",
        lambda root: "fe_share=n/a (test)",
    )

    result = evaluate_green_gate(root, hours=12.0, session_min_pct=-1.0, window_min_pct=-2.0)
    assert result.session_pass is True
    assert result.readiness_pass is True


def test_session_fails_when_below_configured_floor(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_env(root, ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL="false", FE_STABLE_RUNWAY_ENABLED="true")
    _write_followed(root, ["WETH_ALPHA"])
    (root / "control.json").write_text("{}", encoding="utf-8")
    (root / "real_cron.log").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.nano_green.get_current_balance",
        lambda: {"total": 100.0, "source": "test"},
    )
    monkeypatch.setattr(
        "scripts.nano_green.resolve_session_baseline",
        lambda total, reset=False: (132.0, "2026-05-29T00:00:00Z"),
    )
    monkeypatch.setattr(
        "scripts.nano_green._fe_share_line",
        lambda root: "fe_share=n/a (test)",
    )

    result = evaluate_green_gate(root, hours=12.0, session_min_pct=-1.0, window_min_pct=-2.0)
    assert result.session_pass is False


def test_rotation_open_symbols_respects_blocklist(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_followed(root, ["WETH_ALPHA", "WMATIC_ALPHA", "LINK_ALPHA"])
    (root / ".xsignal_blocked_symbols").write_text(
        "WMATIC_ALPHA\nLINK_ALPHA\n",
        encoding="utf-8",
    )
    assert rotation_open_symbols(root) == ["WETH_ALPHA"]
