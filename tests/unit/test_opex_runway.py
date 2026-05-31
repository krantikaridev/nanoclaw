"""Opex runway alert — stables vs monthly burn threshold."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import config as cfg
from nanoclaw import opex_runway as orw


def test_total_monthly_opex_sums_line_items() -> None:
    total = orw.total_monthly_opex_usd(
        opex_monthly=10.0,
        cursor_monthly=20.0,
        grok_monthly=5.0,
        hosting_monthly=3.0,
    )
    assert total == pytest.approx(38.0)


def test_runway_threshold_14_days() -> None:
    monthly = 30.0
    threshold = orw.runway_alert_threshold_usd(monthly, 14)
    assert threshold == pytest.approx((30.0 / 30.0) * 14.0)


def test_assess_runway_alert_when_stables_below_threshold() -> None:
    assessment = orw.assess_opex_runway(
        4.0,
        wallet=cfg.WALLET,
        alert_days=14,
        opex_monthly=10.0,
        cursor_monthly=0.0,
        grok_monthly=0.0,
        hosting_monthly=0.0,
    )
    assert assessment.alert_active is True
    assert assessment.runway_days == pytest.approx(12.0)
    assert assessment.alert_threshold_usd == pytest.approx((10.0 / 30.0) * 14.0)


def test_assess_runway_ok_when_stables_above_threshold() -> None:
    assessment = orw.assess_opex_runway(
        20.0,
        alert_days=14,
        opex_monthly=10.0,
    )
    assert assessment.alert_active is False


def test_format_message_includes_wallet_and_line_items() -> None:
    assessment = orw.assess_opex_runway(
        4.0,
        wallet="0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6",
        alert_days=14,
        opex_monthly=10.0,
        cursor_monthly=5.0,
    )
    msg = orw.format_opex_runway_message(assessment)
    assert "0x05eF" in msg
    assert "FBe6" in msg
    assert "Ankr/RPC misc" in msg
    assert "Cursor" in msg
    assert "runway_days=" in msg


def test_run_opex_runway_check_dry_run_alert(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "OPEX_MONTHLY_USD", 10.0)
    monkeypatch.setattr(cfg, "OPEX_CURSOR_MONTHLY_USD", 0.0)
    monkeypatch.setattr(cfg, "OPEX_GROK_MONTHLY_USD", 0.0)
    monkeypatch.setattr(cfg, "OPEX_HOSTING_MONTHLY_USD", 0.0)
    monkeypatch.setattr(cfg, "OPEX_RUNWAY_ALERT_DAYS", 14)
    assessment, code = orw.run_opex_runway_check(
        stables_usd=3.0,
        dry_run=True,
    )
    assert assessment is not None
    assert assessment.alert_active is True
    assert code == 1
    out = capsys.readouterr().out
    assert "OPEX RUNWAY ALERT" in out


def test_run_opex_runway_check_dry_run_ok(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "OPEX_MONTHLY_USD", 10.0)
    monkeypatch.setattr(cfg, "OPEX_RUNWAY_ALERT_DAYS", 14)
    _assessment, code = orw.run_opex_runway_check(
        stables_usd=50.0,
        dry_run=True,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "OPEX RUNWAY OK" in out


def test_run_opex_runway_check_sends_telegram_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_send = MagicMock()
    monkeypatch.setattr(cfg, "OPEX_MONTHLY_USD", 10.0)
    monkeypatch.setattr(cfg, "OPEX_RUNWAY_ALERT_DAYS", 14)
    monkeypatch.setattr(cfg, "OPEX_RUNWAY_TELEGRAM_ENABLED", True)

    import modules.agent_layer as agent_layer

    monkeypatch.setattr(agent_layer, "_telegram_send_html", mock_send)

    _assessment, code = orw.run_opex_runway_check(
        stables_usd=1.0,
        dry_run=False,
        send_telegram=True,
    )
    assert code == 1
    mock_send.assert_called_once()
    text = mock_send.call_args[0][0]
    assert "OPEX RUNWAY" in text
