"""Tests for copy-trade wallet list audit."""

from __future__ import annotations

import json
from pathlib import Path

import copy_trading
import scripts.copy_trading_audit as audit_cli
from modules.copy_trading_audit import (
    LEGACY_MISCONFIGURED_WALLETS,
    CopyTradingAuditReport,
    audit_followed_wallets,
    classify_wallet,
    filter_tradeable_wallets,
    normalize_address,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

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


def test_repo_followed_wallets_has_no_token_contracts():
    data = json.loads((REPO_ROOT / "followed_wallets.json").read_text(encoding="utf-8"))
    wallets = data.get("wallets", [])
    assert isinstance(wallets, list)
    for addr in wallets:
        category, _ = classify_wallet(str(addr))
        assert category != "token_contract", f"token contract in followed_wallets.json: {addr}"


def test_cli_empty_wallets_enabled_exits_1(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "followed_wallets.json"
    config_path.write_text(json.dumps({"wallets": []}), encoding="utf-8")
    monkeypatch.setattr(audit_cli.cfg, "COPY_TRADING_ENABLED", True)
    monkeypatch.setattr(audit_cli.cfg, "COPY_TRADING_REJECT_TOKEN_CONTRACTS", True)

    code = audit_cli.main(["--config", str(config_path)])

    assert code == 1
    out = capsys.readouterr().out
    assert "tradeable=0" in out
    assert "COPY_TRADING_ENABLED=false" in out


def test_cli_empty_wallets_disabled_exits_0(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "followed_wallets.json"
    config_path.write_text(json.dumps({"wallets": []}), encoding="utf-8")
    monkeypatch.setattr(audit_cli.cfg, "COPY_TRADING_ENABLED", False)

    code = audit_cli.main(["--config", str(config_path)])

    assert code == 0
    assert "tradeable=0" in capsys.readouterr().out


def test_cli_legacy_token_list_exits_2(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "followed_wallets.json"
    config_path.write_text(
        json.dumps({"wallets": list(LEGACY_MISCONFIGURED_WALLETS)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_cli.cfg, "COPY_TRADING_ENABLED", True)

    code = audit_cli.main(["--config", str(config_path)])

    assert code == 2
    out = capsys.readouterr().out
    assert "REJECT token_contract" in out


def test_cli_tradeable_eoa_exits_0(monkeypatch, tmp_path):
    config_path = tmp_path / "followed_wallets.json"
    config_path.write_text(json.dumps({"wallets": [OPERATOR_EOA]}), encoding="utf-8")
    monkeypatch.setattr(audit_cli.cfg, "COPY_TRADING_ENABLED", True)

    code = audit_cli.main(["--config", str(config_path)])

    assert code == 0
