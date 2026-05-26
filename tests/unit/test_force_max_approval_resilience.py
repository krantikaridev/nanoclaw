"""Startup-crash landmine regression: ``_force_max_approval`` must never crash.

Background (2026-05-24 incident): live bot crash-looped on startup when POL
balance (~0.025 POL) was below the gas budget for a single approve tx. The
legacy ``_force_max_approval`` wrapper used to pass ``force=True``, bypassing
the allowance pre-check inside ``ensure_startup_router_approval``. With
allowance already at MAX, the safe behavior is to skip — not to retry an
approve that can't fund itself.

This test file pins the resilient behavior of the wrapper so a regression
(re-adding ``force=True`` or removing pre-checks) is caught in CI.
"""

from __future__ import annotations

from swap_executor import _force_max_approval


def _mock_w3(*, pol: float, gas_gwei: float = 100.0):
    """Same shape as ``tests/unit/test_startup_gas_bootstrap.py::_mock_w3``.

    ``send_raw_transaction`` raises so we catch any code path that attempts a
    broadcast — startup must skip, not broadcast, when allowance is sufficient
    or POL is below the approve budget.
    """

    class _Account:
        address = "0x" + "aa" * 20

    class _EthAccount:
        @staticmethod
        def from_key(_key):
            return _Account()

        @staticmethod
        def sign_transaction(_tx, private_key):
            class _Signed:
                raw_transaction = b"\x01"

            return _Signed()

    class _Eth:
        gas_price = int(gas_gwei * 1e9)
        account = _EthAccount()

        @staticmethod
        def get_balance(_addr):
            return int(pol * 10**18)

        @staticmethod
        def get_transaction_count(_addr):
            return 0

        @staticmethod
        def send_raw_transaction(_raw):
            raise AssertionError("unexpected broadcast — wrapper should have skipped")

    class _W3:
        eth = _Eth()

        @staticmethod
        def from_wei(val, unit):
            if unit == "ether":
                return val / 10**18
            raise ValueError(unit)

        @staticmethod
        def to_checksum_address(addr):
            return addr

    return _W3()


def test_force_max_approval_returns_true_when_allowance_already_max(monkeypatch, capsys):
    monkeypatch.setattr("swap_executor._erc20_allowance", lambda *_a, **_k: 10**30)

    ok = _force_max_approval(
        _mock_w3(pol=1.0),
        "0x" + "11" * 32,
        "0x" + "ee" * 20,
    )

    assert ok is True
    out = capsys.readouterr().out
    assert "Skipped — allowance sufficient" in out


def test_force_max_approval_returns_false_when_pol_below_gas_budget(monkeypatch, capsys):
    monkeypatch.setattr("swap_executor._erc20_allowance", lambda *_a, **_k: 0)
    monkeypatch.setattr("swap_executor.cfg.POL_APPROVE_GAS_UNITS", 85_000)

    ok = _force_max_approval(
        _mock_w3(pol=0.02, gas_gwei=300.0),
        "0x" + "22" * 32,
        "0x" + "ee" * 20,
    )

    assert ok is False
    out = capsys.readouterr().out
    assert "Skipped — insufficient POL for approve" in out


def test_force_max_approval_never_raises_on_low_pol(monkeypatch):
    """Startup must never crash — even if POL is effectively zero."""
    monkeypatch.setattr("swap_executor._erc20_allowance", lambda *_a, **_k: 0)
    monkeypatch.setattr("swap_executor.cfg.POL_APPROVE_GAS_UNITS", 85_000)

    try:
        ok = _force_max_approval(
            _mock_w3(pol=0.0, gas_gwei=500.0),
            "0x" + "33" * 32,
            "0x" + "ee" * 20,
        )
    except Exception as ex:  # noqa: BLE001 — the whole point is "never raises"
        raise AssertionError(f"_force_max_approval raised on low POL: {ex!r}") from ex

    assert ok is False
