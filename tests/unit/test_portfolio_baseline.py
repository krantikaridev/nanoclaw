"""Tests for dynamic nanomon PnL baseline (modules.baseline)."""

import json
from pathlib import Path

import pytest

from modules import baseline as bl


def test_baseline_from_env_overrides_file(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PORTFOLIO_BASELINE_USD", "101.5")
    monkeypatch.delenv("WALLET", raising=False)
    assert bl.resolve_portfolio_baseline_usd(50.0) == 101.5


def test_baseline_env_zero_falls_through_to_json(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PORTFOLIO_BASELINE_USD", "0")
    monkeypatch.setenv("WALLET", "0xAAAABBBBCCCCDDEEEFFFdddddddddddddddddddd")
    (tmp_path / "portfolio_baseline.json").write_text(
        json.dumps(
            {
                "wallet": "0xAAAABBBBCCCCDDEEEFFFdddddddddddddddddddd",
                "baseline_usd": 95.45,
            }
        ),
        encoding="utf-8",
    )
    assert bl.resolve_portfolio_baseline_usd(12.0) == 95.45


def test_baseline_env_zero_falls_through_to_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PORTFOLIO_BASELINE_USD", "0.0")
    monkeypatch.delenv("WALLET", raising=False)
    assert bl.resolve_portfolio_baseline_usd(42.25) == 42.25


def test_baseline_json_when_wallet_matches(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PORTFOLIO_BASELINE_USD", raising=False)
    monkeypatch.setenv("WALLET", "0xAAAABBBBCCCCDDEEEFFFdddddddddddddddddddd")
    (tmp_path / "portfolio_baseline.json").write_text(
        json.dumps(
            {
                "wallet": "0xAAAABBBBCCCCDDEEEFFFdddddddddddddddddddd",
                "baseline_usd": 95.45,
            }
        ),
        encoding="utf-8",
    )
    assert bl.resolve_portfolio_baseline_usd(12.0) == 95.45


def test_baseline_from_csv_first_row(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PORTFOLIO_BASELINE_USD", raising=False)
    monkeypatch.delenv("WALLET", raising=False)
    (tmp_path / "portfolio_history.csv").write_text(
        "timestamp,usdt,usdc,wmatic,pol,pol_usd_price,total_value\n"
        "2026-05-01T00:00:00,10,20,1,0.1,0.1,88.88\n",
        encoding="utf-8",
    )
    assert bl.resolve_portfolio_baseline_usd(99.0) == 88.88


def test_baseline_fallback_last_total(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PORTFOLIO_BASELINE_USD", raising=False)
    monkeypatch.delenv("WALLET", raising=False)
    assert bl.resolve_portfolio_baseline_usd(42.25) == 42.25
