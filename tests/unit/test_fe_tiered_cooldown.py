"""Tiered FE stable-runway re-entry cooldown."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import config as cfg
from modules import swap_executor as se
from nanoclaw import fe_tiered_cooldown as ftc


class _Bal:
    def __init__(
        self,
        *,
        usdt: float = 0.0,
        usdc: float = 0.0,
        total: float = 140.0,
        fe: float = 111.0,
        wmatic: float = 0.0,
    ) -> None:
        self.usdt = usdt
        self.usdc = usdc
        self.total_portfolio_usd = total
        self.followed_equity_usd = fe
        self.wmatic = wmatic
        self.pol = 14.0


def _tiered_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_ENABLED", True)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL", 0.85)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD", 10.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_RESERVE_HEADROOM_USD", 2.0)
    monkeypatch.setattr(se.cfg, "FE_STABLE_RUNWAY_TIERED_MIN_NOTIONAL_USD", 5.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_TIERED_EXEMPT_ENABLED", False)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_USD", 132.0)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_ENABLED", True)
    monkeypatch.setattr(se.cfg, "OPERATING_RESERVE_PCT", 10.0)
    monkeypatch.setattr(se.cfg, "STAGE_SEED_AUTO_SYNC_ENABLED", False)
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED", True)
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_HOURS", 4.0)
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_AFTER_REBUILD", True)


def test_active_cooldown_blocks_tiered_bypass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _tiered_env(monkeypatch)
    state_path = tmp_path / "fe_tiered_cooldown.json"
    monkeypatch.setattr(ftc, "FE_TIERED_COOLDOWN_FILE", state_path)
    now = time.time()
    ftc.record_cooldown(trigger="tiered_fill", stable_usd=19.0, now=now, state_path=state_path)

    bal = _Bal(usdt=0.93, usdc=26.53, total=140.0, fe=111.0)
    ctx = se._fe_stable_runway_tiered_bypass_context(bal, signal_strength=0.87)  # noqa: SLF001
    assert ctx is None
    out = capsys.readouterr().out
    assert "[nanoclaw] FE STABLE RUNWAY TIERED | cooldown" in out
    assert "stable_usd=27.46" in out
    assert "until=" in out


def test_expired_cooldown_allows_tiered_bypass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _tiered_env(monkeypatch)
    state_path = tmp_path / "fe_tiered_cooldown.json"
    monkeypatch.setattr(ftc, "FE_TIERED_COOLDOWN_FILE", state_path)
    start = time.time() - 5 * 3600
    ftc.record_cooldown(trigger="tiered_fill", stable_usd=19.0, now=start, state_path=state_path)

    bal = _Bal(usdt=0.93, usdc=26.53, total=140.0, fe=111.0)
    ctx = se._fe_stable_runway_tiered_bypass_context(bal, signal_strength=0.87)  # noqa: SLF001
    assert ctx is not None
    assert ctx["max_notional_usd"] == pytest.approx(10.0)


def test_rebuild_cooldown_optional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED", True)
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_AFTER_REBUILD", False)
    state_path = tmp_path / "fe_tiered_cooldown.json"

    until = ftc.maybe_record_rebuild_cooldown(stable_usd=14.0, state_path=state_path)
    assert until is None
    assert not state_path.is_file()

    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_AFTER_REBUILD", True)
    until = ftc.maybe_record_rebuild_cooldown(
        stable_usd=14.0,
        now=1_700_000_000.0,
        state_path=state_path,
    )
    assert until is not None
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert raw["last_trigger"] == "rebuild"


def test_cooldown_persisted_under_runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED", True)
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_HOURS", 2.0)
    state_path = tmp_path / ".runtime" / "fe_tiered_cooldown.json"

    ftc.record_cooldown(trigger="tiered_fill", stable_usd=20.0, now=1000.0, state_path=state_path)
    assert state_path.is_file()
    assert ftc.cooldown_active(now=1000.0, state_path=state_path)
    assert not ftc.cooldown_active(now=1000.0 + 2 * 3600 + 1, state_path=state_path)


def test_cooldown_disabled_never_blocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _tiered_env(monkeypatch)
    monkeypatch.setattr(cfg, "FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED", False)
    state_path = tmp_path / "fe_tiered_cooldown.json"
    ftc.record_cooldown(trigger="tiered_fill", stable_usd=19.0, now=1_700_000_000.0, state_path=state_path)

    bal = _Bal(usdt=0.93, usdc=26.53, total=140.0, fe=111.0)
    ctx = se._fe_stable_runway_tiered_bypass_context(bal, signal_strength=0.87)  # noqa: SLF001
    assert ctx is not None
