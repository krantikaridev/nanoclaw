"""Tests for nanoclaw.play_budget daily X-SIGNAL entry cap."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from nanoclaw import play_budget as pb


def _write_log(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_count_xsignal_entry_fills_dedupes_by_tx(tmp_path: Path) -> None:
    day_ts = int(datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc).timestamp())
    log = tmp_path / "real_cron.log"
    tx = "0xabc123"
    _write_log(
        log,
        [
            f"=== CYCLE {day_ts}",
            f"[nanoclaw] TRADE_ATTRIBUTION tx={tx} dir=USDC_TO_EQUITY sz≈9.5 msg=ok",
            f"[nanoclaw] X-SIGNAL STF | EXEC SUCCESS | sym=WETH_ALPHA | tx={tx}",
        ],
    )
    since = datetime(2026, 6, 5, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 6, 6, 0, 0, tzinfo=timezone.utc)
    assert pb.count_xsignal_entry_fills(log, since_utc=since, until_utc=until) == 1


def test_entry_allows_when_under_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_ENABLED", True)
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_MAX_FILLS_PER_UTC_DAY", 2)
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_TOTAL_USD_CEILING", 200.0)
    day_ts = int(datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc).timestamp())
    log = tmp_path / "real_cron.log"
    _write_log(
        log,
        [
            f"=== CYCLE {day_ts}",
            "[nanoclaw] TRADE_ATTRIBUTION tx=0x111 dir=USDC_TO_EQUITY sz≈8 msg=ok",
        ],
    )
    now = datetime(2026, 6, 5, 15, 0, tzinfo=timezone.utc)
    allowed, reason = pb.entry_allows(total_usd=135.0, log_path=log, now_utc=now)
    assert allowed is True
    assert reason is None


def test_entry_blocks_after_two_fills(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_ENABLED", True)
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_MAX_FILLS_PER_UTC_DAY", 2)
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_TOTAL_USD_CEILING", 200.0)
    day_ts = int(datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc).timestamp())
    log = tmp_path / "real_cron.log"
    _write_log(
        log,
        [
            f"=== CYCLE {day_ts}",
            "[nanoclaw] TRADE_ATTRIBUTION tx=0x111 dir=USDC_TO_EQUITY sz≈8 msg=ok",
            "[nanoclaw] TRADE_ATTRIBUTION tx=0x222 dir=USDC_TO_EQUITY sz≈9 msg=ok",
        ],
    )
    now = datetime(2026, 6, 5, 15, 0, tzinfo=timezone.utc)
    allowed, reason = pb.entry_allows(total_usd=135.0, log_path=log, now_utc=now)
    assert allowed is False
    assert reason is not None
    assert "play_budget_exhausted" in reason


def test_entry_inactive_when_total_at_ceiling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_ENABLED", True)
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_TOTAL_USD_CEILING", 200.0)
    log = tmp_path / "real_cron.log"
    allowed, reason = pb.entry_allows(total_usd=210.0, log_path=log)
    assert allowed is True
    assert reason is None


def test_entry_inactive_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pb.cfg, "PLAY_BUDGET_ENABLED", False)
    log = tmp_path / "real_cron.log"
    allowed, reason = pb.entry_allows(total_usd=80.0, log_path=log)
    assert allowed is True
