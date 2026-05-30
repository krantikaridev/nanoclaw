"""Tests for copy-trade wallet list audit."""

from __future__ import annotations

import copy_trading
from modules.copy_trading_audit import (
    LEGACY_MISCONFIGURED_WALLETS,
    CopyTradingAuditReport,
    audit_followed_wallets,
    classify_wallet,
    filter_tradeable_wallets,
    normalize_address,
)

OPERATOR_EOA = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"
USDC_POLYGON = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"


def test_normalize_address_lowercases():
    assert normalize_address(USDC_POLYGON) == USDC_POLYGON.lower()


def test_classify_usdc_as_token_contract():
    category, label = classify_wallet(USDC_POLYGON)
    assert category == "token_contract"
    assert label == "USDC"


def test_classify_operator_eoa_tradeable():
    category, label = classify_wallet(OPERATOR_EOA)
    assert category == "tradeable"
    assert label is None


def test_legacy_misconfigured_list_all_tokens():
    report = audit_followed_wallets(list(LEGACY_MISCONFIGURED_WALLETS))
    assert report.tradeable == []
    assert len(report.token_contracts) == len(LEGACY_MISCONFIGURED_WALLETS)
    assert report.exit_code == 2


def test_audit_mixed_list_keeps_eoa():
    report = audit_followed_wallets([USDC_POLYGON, OPERATOR_EOA])
    assert report.tradeable == [normalize_address(OPERATOR_EOA)]
    assert report.exit_code == 0


def test_audit_enabled_empty_list_exit_1():
    report = audit_followed_wallets([], copy_trading_enabled=True)
    assert report.exit_code == 1


def test_audit_disabled_empty_list_exit_0():
    report = audit_followed_wallets([], copy_trading_enabled=False)
    assert report.ok_for_copy_trading is True
    assert report.exit_code == 0


def test_filter_tradeable_wallets_strips_tokens():
    out = filter_tradeable_wallets([USDC_POLYGON, OPERATOR_EOA])
    assert out == [normalize_address(OPERATOR_EOA)]


def test_get_target_wallets_filters_token_contracts(monkeypatch, tmp_path, capsys):
    config = {
        "wallets": [USDC_POLYGON, OPERATOR_EOA],
        "max_copy_ratio": 0.08,
    }
    path = tmp_path / "followed_wallets.json"
    path.write_text(__import__("json").dumps(config), encoding="utf-8")
    monkeypatch.setattr(copy_trading, "CONFIG_FILE", str(path))
    monkeypatch.setattr(copy_trading.cfg, "COPY_TRADING_REJECT_TOKEN_CONTRACTS", True)
    copy_trading._warned_misconfig = False

    wallets = copy_trading.get_target_wallets()
    assert wallets == [normalize_address(OPERATOR_EOA)]
    captured = capsys.readouterr()
    assert "rejected 1 non-tradeable" in captured.out


def test_copy_trading_audit_report_lines_include_action_when_empty():
    report = CopyTradingAuditReport(
        wallets=[],
        copy_trading_enabled=True,
    )
    text = "\n".join(report.lines())
    assert "ACTION:" in text
    assert "COPY_TRADING_AUDIT.md" in text
