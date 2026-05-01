import asyncio

import swap_executor


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
