"""Unit tests for .xsignal_blocked_symbols and X_SIGNAL_HONOR_FULL_BLOCKLIST."""

from __future__ import annotations

import config as cfg
from nanoclaw.strategies.signal_equity_trader import FollowedEquity


def _blocked_assets() -> list[FollowedEquity]:
    return [
        FollowedEquity("WBTC_ALPHA", "0x" + "1" * 40, 8),
        FollowedEquity("LINK_ALPHA", "0x" + "2" * 40, 18),
    ]


def test_filter_all_blocked_honor_full_blocklist_true_returns_empty(
    tmp_path, monkeypatch, capsys
):
    from modules import signal as signal_module

    (tmp_path / ".xsignal_blocked_symbols").write_text("WBTC_ALPHA\nLINK_ALPHA\n")
    monkeypatch.setattr(signal_module, "_xsignal_block_list_search_roots", lambda: [tmp_path])
    signal_module._XSIGNAL_BLOCKED_CACHE = None
    monkeypatch.setattr(cfg, "X_SIGNAL_HONOR_FULL_BLOCKLIST", True)

    out = signal_module._filter_xsignal_blocked_equities(
        _blocked_assets(),
        log_skips=False,
    )

    assert out == []
    captured = capsys.readouterr().out
    assert "All followed assets blocked" in captured
    assert "operator block honored" in captured
    assert "ignoring blocks this cycle" not in captured


def test_filter_all_blocked_honor_full_blocklist_false_ignores_blocks(
    tmp_path, monkeypatch, capsys
):
    from modules import signal as signal_module

    (tmp_path / ".xsignal_blocked_symbols").write_text("WBTC_ALPHA\nLINK_ALPHA\n")
    monkeypatch.setattr(signal_module, "_xsignal_block_list_search_roots", lambda: [tmp_path])
    signal_module._XSIGNAL_BLOCKED_CACHE = None
    monkeypatch.setattr(cfg, "X_SIGNAL_HONOR_FULL_BLOCKLIST", False)

    out = signal_module._filter_xsignal_blocked_equities(
        _blocked_assets(),
        log_skips=False,
    )

    assert len(out) == 2
    assert "ignoring blocks this cycle" in capsys.readouterr().out


def test_filter_all_blocked_loss_cut_path_unchanged(tmp_path, monkeypatch):
    from modules import signal as signal_module

    (tmp_path / ".xsignal_blocked_symbols").write_text("LINK_ALPHA\n")
    monkeypatch.setattr(signal_module, "_xsignal_block_list_search_roots", lambda: [tmp_path])
    signal_module._XSIGNAL_BLOCKED_CACHE = None
    monkeypatch.setattr(cfg, "X_SIGNAL_HONOR_FULL_BLOCKLIST", False)

    assets = [FollowedEquity("LINK_ALPHA", "0x" + "2" * 40, 18)]
    out = signal_module._filter_xsignal_blocked_equities(
        assets,
        log_skips=False,
        allow_ignore_all_blocked=False,
    )
    assert out == []
