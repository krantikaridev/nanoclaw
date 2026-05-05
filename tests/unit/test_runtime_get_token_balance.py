"""get_token_balance visibility when RPC / contract calls fail."""

from __future__ import annotations

import modules.runtime as runtime


def test_get_token_balance_logs_and_returns_zero_when_call_raises(capsys, monkeypatch):
    class FakeContract:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        class _Fns:
            def balanceOf(self, _wallet: str):
                return self

            def call(self):
                raise OSError("rpc simulated failure")

        functions = _Fns()

    class FakeEth:
        def contract(self, **kwargs: object):
            return FakeContract()

    class FakeWeb3:
        eth = FakeEth()

    tok = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
    wal = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"

    out = runtime.get_token_balance(tok, 18, web3_client=FakeWeb3(), wallet_address=wal)
    assert out == 0.0
    err = capsys.readouterr().out
    assert "BALANCE READ FAILED" in err
    assert "OSError" in err
    assert "rpc simulated failure" in err
