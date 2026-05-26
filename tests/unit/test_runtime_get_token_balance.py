"""get_token_balance visibility when RPC / contract calls fail."""

from __future__ import annotations

import pytest

import modules.runtime as runtime


class _RaisingWeb3:
    """Fake web3 client whose ``balanceOf().call()`` always raises."""

    def __init__(self, exc_class: type[BaseException] = OSError, msg: str = "rpc simulated failure") -> None:
        self._exc_class = exc_class
        self._msg = msg

    class _Fns:
        def __init__(self, exc_class: type[BaseException], msg: str) -> None:
            self._exc_class = exc_class
            self._msg = msg

        def balanceOf(self, _wallet: str):
            return self

        def call(self):
            raise self._exc_class(self._msg)

    class _Contract:
        def __init__(self, exc_class: type[BaseException], msg: str) -> None:
            self.functions = _RaisingWeb3._Fns(exc_class, msg)

    class _Eth:
        def __init__(self, exc_class: type[BaseException], msg: str) -> None:
            self._exc_class = exc_class
            self._msg = msg

        def contract(self, **kwargs: object):
            return _RaisingWeb3._Contract(self._exc_class, self._msg)

    @property
    def eth(self):  # noqa: D401
        return _RaisingWeb3._Eth(self._exc_class, self._msg)


@pytest.fixture(autouse=True)
def _reset_balance_read_fail_latch():
    """Clear the once-logged latch between tests so each starts clean."""
    runtime._reset_balance_read_fail_logged()
    yield
    runtime._reset_balance_read_fail_logged()


def test_get_token_balance_logs_and_returns_zero_when_call_raises(capsys):
    tok = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
    wal = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"

    out = runtime.get_token_balance(tok, 18, web3_client=_RaisingWeb3(), wallet_address=wal)
    assert out == 0.0
    err = capsys.readouterr().out
    assert "BALANCE READ FAILED" in err
    assert "OSError" in err
    assert "rpc simulated failure" in err


def test_get_token_balance_failure_logs_once_per_token_then_suppresses(capsys):
    """Acceptance criterion E: a broken contract emits BALANCE READ FAILED ONCE,
    then stays silent for the rest of the process lifetime.

    Pre-cleanup, WBTC_ALPHA (0x1BFD6703…6C834E, BadFunctionCallOutput) emitted
    the line every inventory cycle. The blocklist in .xsignal_blocked_symbols
    only gates trading, not inventory reads, so the spam continued indefinitely.
    """
    tok = "0x1BFD67037B42Cf73acf204706795bF64736C834e"
    wal = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"
    client = _RaisingWeb3(exc_class=RuntimeError, msg="BadFunctionCallOutput")

    for _ in range(5):
        out = runtime.get_token_balance(tok, 8, web3_client=client, wallet_address=wal)
        assert out == 0.0

    captured = capsys.readouterr().out
    assert captured.count("BALANCE READ FAILED") == 1
    assert "further failures for this token+wallet suppressed" in captured
    assert "BadFunctionCallOutput" in captured


def test_get_token_balance_failure_latch_is_per_token(capsys):
    """A second broken token must still log once -- the latch is per (token, wallet)."""
    wal = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"
    tok_a = "0x1BFD67037B42Cf73acf204706795bF64736C834e"
    tok_b = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
    client = _RaisingWeb3(exc_class=RuntimeError, msg="BadFunctionCallOutput")

    runtime.get_token_balance(tok_a, 8, web3_client=client, wallet_address=wal)
    runtime.get_token_balance(tok_a, 8, web3_client=client, wallet_address=wal)  # latched
    runtime.get_token_balance(tok_b, 18, web3_client=client, wallet_address=wal)
    runtime.get_token_balance(tok_b, 18, web3_client=client, wallet_address=wal)  # latched

    captured = capsys.readouterr().out
    # Exactly two BALANCE READ FAILED lines: one per token, despite four total
    # call attempts.
    assert captured.count("BALANCE READ FAILED") == 2


def test_get_token_balance_failure_latch_is_per_wallet(capsys):
    """Same token but different wallets must each get one log line.

    Defends against a cache key that drops the wallet, which would silence
    legitimate diagnostics for a fresh wallet after the first failure.
    """
    tok = "0x1BFD67037B42Cf73acf204706795bF64736C834e"
    wal_a = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"
    wal_b = "0x1234567890abcDEF1234567890abcdef12345678"
    client = _RaisingWeb3(exc_class=RuntimeError, msg="BadFunctionCallOutput")

    runtime.get_token_balance(tok, 8, web3_client=client, wallet_address=wal_a)
    runtime.get_token_balance(tok, 8, web3_client=client, wallet_address=wal_a)  # latched
    runtime.get_token_balance(tok, 8, web3_client=client, wallet_address=wal_b)
    runtime.get_token_balance(tok, 8, web3_client=client, wallet_address=wal_b)  # latched

    captured = capsys.readouterr().out
    assert captured.count("BALANCE READ FAILED") == 2
