import asyncio

import swap_executor


class _FakeCall:
    def __init__(self, out=None, err=None):
        self._out = out
        self._err = err

    def call(self):
        if self._err is not None:
            raise self._err
        return self._out


class _FakeFunctions:
    def __init__(self, responses):
        self._responses = responses

    def getAmountsOut(self, _amount_in, path):
        key = tuple(path)
        response = self._responses[key]
        if isinstance(response, Exception):
            return _FakeCall(err=response)
        return _FakeCall(out=response)


class _FakeRouterContract:
    def __init__(self, responses):
        self.functions = _FakeFunctions(responses)


class _FakeEth:
    def __init__(self, responses):
        self._responses = responses

    def contract(self, address, abi):
        _ = (address, abi)
        return _FakeRouterContract(self._responses)


class _FakeW3:
    def __init__(self, responses):
        self.eth = _FakeEth(responses)


def test_best_quote_path_picks_highest_output_and_applies_slippage(monkeypatch):
    monkeypatch.setattr(swap_executor, "SWAP_SLIPPAGE_BPS", 100)
    p1 = [swap_executor.USDC, swap_executor.WMATIC]
    p2 = [swap_executor.USDC, swap_executor.USDT, swap_executor.WMATIC]
    responses = {
        tuple(p1): [1, 1000],
        tuple(p2): [1, 1300, 1200],
    }

    best_path, best_amt, min_out = swap_executor._best_quote_path(
        _FakeW3(responses),
        router=swap_executor.ROUTER,
        amount_in=1,
        paths=[p1, p2],
    )

    assert best_path == p2
    assert best_amt == 1200
    assert min_out == 1188


def test_best_quote_path_skips_failed_path_and_uses_next_working_path():
    p1 = [swap_executor.USDC, swap_executor.WMATIC]
    p2 = [swap_executor.USDC, swap_executor.USDT, swap_executor.WMATIC]
    responses = {
        tuple(p1): RuntimeError("pair missing"),
        tuple(p2): [1, 1200, 900],
    }

    best_path, best_amt, min_out = swap_executor._best_quote_path(
        _FakeW3(responses),
        router=swap_executor.ROUTER,
        amount_in=1,
        paths=[p1, p2],
    )

    assert best_path == p2
    assert best_amt == 900
    assert min_out > 0


def test_best_quote_path_raises_when_no_paths_are_quotable():
    p1 = [swap_executor.USDC, swap_executor.WMATIC]
    responses = {tuple(p1): RuntimeError("router failed")}

    try:
        swap_executor._best_quote_path(
            _FakeW3(responses),
            router=swap_executor.ROUTER,
            amount_in=1,
            paths=[p1],
        )
    except RuntimeError as exc:
        assert "No quotable router path" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for all-failing quote paths")


def test_best_quote_path_accepts_explicit_slippage_bps(monkeypatch):
    monkeypatch.setattr(swap_executor, "SWAP_SLIPPAGE_BPS", 100)
    p1 = [swap_executor.USDC, swap_executor.WMATIC]
    responses = {tuple(p1): [1, 1000]}

    _path, best_amt, min_out = swap_executor._best_quote_path(
        _FakeW3(responses),
        router=swap_executor.ROUTER,
        amount_in=1,
        paths=[p1],
        slippage_bps=250,
    )

    assert best_amt == 1000
    assert min_out == 975


def test_best_quote_path_caps_slippage_and_enforces_min_out_floor(monkeypatch):
    monkeypatch.setattr(swap_executor, "SWAP_SLIPPAGE_BPS", 15000)
    p1 = [swap_executor.USDC, swap_executor.WMATIC]
    responses = {tuple(p1): [1, 1000]}

    _best_path, best_amt, min_out = swap_executor._best_quote_path(
        _FakeW3(responses),
        router=swap_executor.ROUTER,
        amount_in=1,
        paths=[p1],
    )

    assert best_amt == 1000
    assert min_out == 1


def test_approve_and_swap_returns_none_when_private_key_missing(monkeypatch):
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)

    out = asyncio.run(
        swap_executor.approve_and_swap(
            w3=None,
            private_key=None,
            amount_in=1,
            direction="USDT_TO_WMATIC",
        )
    )

    assert out is None


def test_approve_and_swap_prefers_polygon_private_key_over_other_sources(monkeypatch):
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "polygon-key")
    monkeypatch.setenv("PRIVATE_KEY", "legacy-key")
    key, source = swap_executor._resolve_private_key("arg-key")
    assert key == "polygon-key"
    assert source == "POLYGON_PRIVATE_KEY"


def test_approve_and_swap_does_not_use_function_arg_when_env_keys_missing(monkeypatch):
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)

    key, source = swap_executor._resolve_private_key("arg-key")
    assert key == ""
    assert source == "missing"


def test_resolve_private_key_uses_legacy_when_polygon_missing(monkeypatch):
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("PRIVATE_KEY", "legacy-key")
    key, source = swap_executor._resolve_private_key("arg-key")
    assert key == "legacy-key"
    assert source == "PRIVATE_KEY"


def test_approve_and_swap_returns_none_for_unsupported_direction():
    out = asyncio.run(
        swap_executor.approve_and_swap(
            w3=None,
            private_key="dummy-key",
            amount_in=1,
            direction="UNSUPPORTED_DIRECTION",
        )
    )

    assert out is None


def test_approve_and_swap_returns_none_for_usdc_to_equity_without_token_out():
    out = asyncio.run(
        swap_executor.approve_and_swap(
            w3=None,
            private_key="dummy-key",
            amount_in=1,
            direction="USDC_TO_EQUITY",
        )
    )

    assert out is None


def test_approve_and_swap_returns_none_for_equity_to_usdc_without_token_in():
    out = asyncio.run(
        swap_executor.approve_and_swap(
            w3=None,
            private_key="dummy-key",
            amount_in=1,
            direction="EQUITY_TO_USDC",
        )
    )

    assert out is None


def test_approve_and_swap_returns_none_when_direction_resolves_empty_token(monkeypatch):
    monkeypatch.setattr(swap_executor, "USDT", "")

    out = asyncio.run(
        swap_executor.approve_and_swap(
            w3=None,
            private_key="dummy-key",
            amount_in=1,
            direction="USDT_TO_WMATIC",
        )
    )

    assert out is None


def test_approve_and_swap_returns_none_when_token_in_equals_token_out():
    out = asyncio.run(
        swap_executor.approve_and_swap(
            w3=object(),
            private_key="dummy-key",
            amount_in=1,
            direction="USDT_TO_WMATIC",
            token_in=swap_executor.USDC,
            token_out=swap_executor.USDC,
        )
    )

    assert out is None


def test_approve_and_swap_uses_router_fallback_when_oneinch_key_missing(monkeypatch):
    monkeypatch.delenv("ONEINCH_API_KEY", raising=False)
    monkeypatch.delenv("INCH_API_KEY", raising=False)
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)

    called = {"v3_quote": False}

    def _fake_v3_quote(*_args, **_kwargs):
        called["v3_quote"] = True
        raise RuntimeError("v3 quote called")

    monkeypatch.setattr(swap_executor, "_quote_uniswap_v3_exact_input_single", _fake_v3_quote)
    monkeypatch.setattr(
        swap_executor,
        "_oneinch_swap_payload",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("1inch should not be called without key")),
    )

    out = asyncio.run(
        swap_executor.approve_and_swap(
            w3=object(),
            private_key="dummy-key",
            amount_in=1,
            direction="USDT_TO_WMATIC",
        )
    )

    assert out is None
    assert called["v3_quote"] is True
