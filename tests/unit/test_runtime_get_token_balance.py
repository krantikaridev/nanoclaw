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
    the line every inventory cycle. Blocklisted symbols now skip balanceOf in
    the FE_USD scan; this test covers non-blocked unreadable contracts.
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


class _FakeFollowedAsset:
    def __init__(self, symbol: str, addr: str, decimals: int) -> None:
        self.symbol = symbol
        self.token_address = addr
        self.decimals = decimals


def test_followed_equity_scan_skips_balance_of_for_broken_wbtc_contract(monkeypatch, capsys, tmp_path):
    """FE_USD scan skips Polygon WBTC contract (BadFunctionCallOutput); not trading blocklist."""
    wbtc = _FakeFollowedAsset(
        symbol="WBTC_ALPHA",
        addr="0x1BFD67037B42Cf73acf204706795bF64736C834e",
        decimals=8,
    )
    monkeypatch.setattr(
        runtime,
        "FE_USD_SPOT_CACHE_FILE",
        str(tmp_path / "fe_usd_spot_cache.json"),
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [wbtc],
    )

    def _balance_must_not_run(*_args, **_kwargs):
        raise AssertionError("get_token_balance must not run for broken WBTC contract")

    monkeypatch.setattr(runtime, "get_token_balance", _balance_must_not_run)

    assert runtime._followed_equity_tokens_usdt_usd() == 0.0
    assert "BALANCE READ FAILED" not in capsys.readouterr().out


def test_followed_equity_scan_still_reads_balance_when_symbol_blocked_for_trading(
    monkeypatch, tmp_path
):
    """X-SIGNAL blocklist must not zero FE_USD for held WETH (TOTAL accounting)."""
    weth = _FakeFollowedAsset(
        symbol="WETH_ALPHA",
        addr="0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        decimals=18,
    )
    monkeypatch.setattr(
        runtime,
        "FE_USD_SPOT_CACHE_FILE",
        str(tmp_path / "fe_usd_spot_cache.json"),
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [weth],
    )
    monkeypatch.setattr(
        "modules.signal.load_xsignal_blocked_symbols",
        lambda: (frozenset({"WETH_ALPHA"}), ".xsignal_blocked_symbols"),
    )
    monkeypatch.setattr(runtime, "get_token_balance", lambda *_a, **_k: 0.0557)
    monkeypatch.setattr(runtime, "_quote_followed_token_usdt_mtm", lambda *_a, **_k: 112.0)

    assert runtime._followed_equity_tokens_usdt_usd() == pytest.approx(112.0)


def test_followed_equity_scan_broken_wbtc_skip_preserves_log_once_for_other_failures(
    monkeypatch, capsys, tmp_path
):
    """Broken WBTC address skips balanceOf; other contracts still log once on failure."""
    blocked = _FakeFollowedAsset(
        symbol="WBTC_ALPHA",
        addr="0x1BFD67037B42Cf73acf204706795bF64736C834e",
        decimals=8,
    )
    readable = _FakeFollowedAsset(
        symbol="LINK_ALPHA",
        addr="0x53E0bca35eC356Bd5DdDFebbD1Fc0FD03FaBad39",
        decimals=18,
    )
    monkeypatch.setattr(
        runtime,
        "FE_USD_SPOT_CACHE_FILE",
        str(tmp_path / "fe_usd_spot_cache.json"),
    )
    monkeypatch.setattr(
        runtime.X_SIGNAL_EQUITY_TRADER,
        "load_followed_equities",
        lambda: [blocked, readable],
    )
    client = _RaisingWeb3(exc_class=RuntimeError, msg="BadFunctionCallOutput")
    orig_get_token_balance = runtime.get_token_balance

    def _balance_for_readable_only(token_address, decimals, **kwargs):
        if str(token_address).lower() == readable.token_address.lower():
            return orig_get_token_balance(
                token_address, decimals, web3_client=client, wallet_address=runtime.WALLET
            )
        raise AssertionError("get_token_balance must not run for broken WBTC contract")

    monkeypatch.setattr(runtime, "get_token_balance", _balance_for_readable_only)
    monkeypatch.setattr(runtime, "_quote_followed_token_usdt_mtm", lambda *_a, **_k: 0.0)

    for _ in range(3):
        runtime._followed_equity_tokens_usdt_usd()

    captured = capsys.readouterr().out
    assert captured.count("BALANCE READ FAILED") == 1
    assert "BadFunctionCallOutput" in captured
