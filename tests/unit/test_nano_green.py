"""Tests for scripts/nano_green.py — configurable window + session floor."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.nano_green import (
    _pause_exec_check,
    _pause_exec_scan_lines,
    _runway_lines,
    evaluate_green_gate,
    rotation_open_symbols,
)


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


def test_pause_exec_fails_when_exec_after_pause_even_if_control_unpaused(tmp_path: Path) -> None:
    """Fills during the paused window before clearance still fail even if control.json says unpaused."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "control.json").write_text(json.dumps({"paused": False}), encoding="utf-8")
    (root / "real_cron.log").write_text(
        "\n".join(
            [
                "[CONTROL] paused=True → skipping new entry trades",
                "[nanoclaw] X-SIGNAL STF | EXEC SUCCESS | sym=WMATIC_ALPHA | tx=0xabc",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ok, detail = _pause_exec_check(root, paused=False)
    assert ok is False
    assert "EXEC SUCCESS in paused window" in detail


def test_pause_exec_passes_after_auto_unpause_clears_prior_pause(tmp_path: Path) -> None:
    """Legitimate fills after auto_unpause must not keep pause_exec on FAIL."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "control.json").write_text(
        json.dumps({"paused": False, "reason": "auto_unpause | window=12h | session≥-1.0%"}),
        encoding="utf-8",
    )
    (root / "real_cron.log").write_text(
        "\n".join(
            [
                "[CONTROL] paused=True → skipping new entry trades",
                "[CONTROL] External layer reason: auto_unpause | window=12h | session≥-1.0%",
                "[CONTROL] paused=False → entry trades allowed when other gates pass",
                "[nanoclaw] X-SIGNAL STF | EXEC SUCCESS | sym=WETH_ALPHA | tx=0xdef",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ok, detail = _pause_exec_check(root, paused=False)
    assert ok is True
    assert "cleared after auto_unpause" in detail


def test_pause_exec_fails_discipline_breach_after_brief_unpause(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "control.json").write_text(
        json.dumps({"paused": True, "reason": "auto_pause | fill while paused (discipline breach)"}),
        encoding="utf-8",
    )
    (root / "real_cron.log").write_text(
        "\n".join(
            [
                "[CONTROL] paused=True → skipping new entry trades",
                "[CONTROL] External layer reason: auto_unpause | window=12h",
                "[nanoclaw] X-SIGNAL STF | EXEC SUCCESS | sym=WMATIC_ALPHA | tx=0xabc",
                "[CONTROL] paused=True → skipping new entry trades",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ok, detail = _pause_exec_check(root, paused=True)
    assert ok is False
    assert "EXEC SUCCESS in paused window" in detail


def test_pause_exec_passes_when_unpaused_and_no_exec_after_marker(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "control.json").write_text(json.dumps({"paused": False}), encoding="utf-8")
    (root / "real_cron.log").write_text(
        "[CONTROL] paused=True → skipping new entry trades\n",
        encoding="utf-8",
    )

    ok, detail = _pause_exec_check(root, paused=False)
    assert ok is True
    assert "no EXEC SUCCESS" in detail


def test_pause_exec_scan_lines_bounds_cleared_unpause() -> None:
    lines = [
        "[CONTROL] paused=True",
        "noise",
        "[CONTROL] External layer reason: auto_unpause | window=12h",
        "[nanoclaw] EXEC SUCCESS | sym=WETH_ALPHA",
    ]
    scanned = _pause_exec_scan_lines(
        lines, 0, paused=False, control_reason="auto_unpause", last_pause_idx=0
    )
    assert scanned == ["noise"]


def test_green_gate_overall_fails_when_exec_after_pause_while_control_unpaused(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_env(root, ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL="false", FE_STABLE_RUNWAY_ENABLED="true")
    _write_followed(root, ["WETH_ALPHA"])
    (root / "control.json").write_text(json.dumps({"paused": False}), encoding="utf-8")
    (root / "real_cron.log").write_text(
        "\n".join(
            [
                "[CONTROL] paused=True → skipping new entry trades",
                "[nanoclaw] X-SIGNAL STF | EXEC SUCCESS | sym=WMATIC_ALPHA | tx=0xabc",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.nano_green.get_current_balance",
        lambda: {"total": 131.0, "source": "test"},
    )
    monkeypatch.setattr(
        "scripts.nano_green.resolve_session_baseline",
        lambda total, reset=False: (130.0, "2026-05-29T00:00:00Z"),
    )
    monkeypatch.setattr(
        "scripts.nano_green._window_pnl_check",
        lambda *a, **k: (True, "PASS | 12h window (test)"),
    )
    monkeypatch.setattr(
        "scripts.nano_green._fe_share_line",
        lambda root: "fe_share=n/a (test)",
    )

    result = evaluate_green_gate(root, hours=12.0, session_min_pct=-1.0, window_min_pct=-2.0)
    assert result.pause_pass is False
    assert result.overall_pass is False


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
