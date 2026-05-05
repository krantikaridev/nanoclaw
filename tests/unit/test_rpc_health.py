from __future__ import annotations

import pytest

from nanoclaw.rpc_health import EXPECTED_POLYGON_POS_CHAIN_ID, check_polygon_pos_rpc


def test_check_polygon_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Eth:
        chain_id = EXPECTED_POLYGON_POS_CHAIN_ID
        block_number = 12_345

    class _W3:
        eth = _Eth()

    monkeypatch.setattr("nanoclaw.config.connect_web3", lambda **k: _W3())
    ok, msg = check_polygon_pos_rpc(timeout=5)
    assert ok is True
    assert "block=12345" in msg


def test_check_wrong_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Eth:
        chain_id = 80_001
        block_number = 1

    class _W3:
        eth = _Eth()

    monkeypatch.setattr("nanoclaw.config.connect_web3", lambda **k: _W3())
    ok, msg = check_polygon_pos_rpc(timeout=5)
    assert ok is False
    assert "wrong chain_id" in msg


def test_check_connect_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**k: object) -> None:
        raise RuntimeError("all endpoints failed")

    monkeypatch.setattr("nanoclaw.config.connect_web3", _boom)
    ok, msg = check_polygon_pos_rpc(timeout=5)
    assert ok is False
    assert "RPC connect failed" in msg
