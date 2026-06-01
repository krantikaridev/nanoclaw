"""Trade attribution log format."""

from __future__ import annotations

from modules import attribution


def test_log_trade_attribution_usd_notional(capsys) -> None:
    attribution.log_trade_attribution(
        tx_hash_hex="0xabc",
        direction="WMATIC_TO_USDC",
        amount_in=89982600000000000000000,
        trade_size=8.99,
        message="swap ok",
    )
    out = capsys.readouterr().out
    assert "sz≈8.99" in out
    assert "899826" not in out


def test_log_trade_attribution_falls_back_to_amount_in(capsys) -> None:
    attribution.log_trade_attribution(
        tx_hash_hex="0xdef",
        direction="WMATIC_TO_USDC",
        amount_in=12345,
        trade_size=0.0,
        message="legacy",
    )
    out = capsys.readouterr().out
    assert "amount_in=12345" in out
    assert "sz≈1.2345e+04" not in out
