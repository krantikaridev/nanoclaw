"""Tests for scripts/nano_green.py — configurable window + session floor."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.nano_green import _runway_lines, evaluate_green_gate, rotation_open_symbols


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


def test_runway_lines_scoped_to_window_with_timestamps(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    old_cycle = int((now.timestamp()) - (24 * 3600))
    new_cycle = int(now.timestamp() - 3600)

    (root / "real_cron.log").write_text(
        "\n".join(
            [
                f"[nanoclaw] === CYCLE {old_cycle} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "[nanoclaw] FE STABLE RUNWAY TIERED | allow USDC→EQUITY BUY | stable_usd=18.00 | fe_share=0.85 | signal=0.90 | max_notional=$10.00",
                f"[nanoclaw] === CYCLE {new_cycle} | BALANCES: USDT=$1 USDC=$1 WMATIC=$1 ===",
                "[nanoclaw] FE STABLE RUNWAY | defer USDC→EQUITY BUY | stable_usd=13.00 | fe_share=0.89",
                "[nanoclaw] FE STABLE RUNWAY TIERED | cooldown | stable_usd=13.00 | until=2026-06-01T16:00:00Z",
                "[nanoclaw] FE STABLE RUNWAY DERISK | evaluate | fe_share=0.74 | dynamic_trim_usd=12.00",
                "[nanoclaw] FE STABLE RUNWAY DERISK | exec plan | sym=WETH_ALPHA | sell_fraction=0.0938 | stable_usd=26.00 | fe_share=0.74 | max_trim_usd=12.00 | window_stress=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    lines = _runway_lines(root, hours=12.0, n=5, now=now)
    assert len(lines) == 4
    assert all("TIERED | allow" not in ln for ln in lines)
    assert lines[0].startswith("2026-06-01T11:00:00Z | ")
    assert "defer USDC→EQUITY BUY" in lines[0]
    assert lines[1].startswith("2026-06-01T11:00:00Z | ")
    assert "TIERED | cooldown" in lines[1]
    assert "[evaluate]" in lines[2]
    assert "dynamic_trim_usd=12.00" in lines[2]
    assert "[exec-plan]" in lines[3]
    assert "sym=WETH_ALPHA" in lines[3]
