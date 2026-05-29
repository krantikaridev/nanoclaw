"""Startup approval + dynamic POL reserve (gas bootstrap)."""

from __future__ import annotations

import pytest

from modules import runtime as rt
from swap_executor import ensure_startup_router_approval


@pytest.fixture(autouse=True)
def _reset_auto_pol_state():
    rt._AUTO_POL_FAILURE_STATE["next_retry_ts"] = 0.0
    rt._AUTO_POL_FAILURE_STATE["consecutive_failures"] = 0.0
    yield
    rt._AUTO_POL_FAILURE_STATE["next_retry_ts"] = 0.0
    rt._AUTO_POL_FAILURE_STATE["consecutive_failures"] = 0.0


@pytest.fixture
def _stage_gas_knobs(monkeypatch):
    monkeypatch.setattr(rt, "MIN_POL_FOR_GAS", 0.005)
    monkeypatch.setattr(rt, "URGENT_GWEI", 120.0)
    monkeypatch.setattr(rt, "POL_SWAP_GAS_UNITS", 450_000)
    monkeypatch.setattr(rt, "POL_GAS_RESERVE_MULTIPLIER", 1.30)
    monkeypatch.setattr(rt, "POL_GAS_RESERVE_BUFFER_POL", 0.005)
    monkeypatch.setattr(rt.GAS_PROTECTOR, "get_gas_price_gwei", lambda: 120.0)


def test_effective_pol_floor_uses_dynamic_reserve_when_static_floor_too_low(_stage_gas_knobs):
    floor = rt.effective_pol_floor(urgent=True, gas_gwei=120.0)
    assert floor == pytest.approx(0.0752, rel=1e-3)
    assert floor > 0.005


def test_maybe_auto_topup_pol_triggers_when_pol_above_static_but_below_dynamic(
    monkeypatch, capsys, _stage_gas_knobs
):
    monkeypatch.setattr(rt, "AUTO_TOPUP_POL", True)
    monkeypatch.setattr(rt, "get_pol_balance", lambda: 0.025)
    monkeypatch.setattr(
        rt,
        "ensure_pol_for_trade",
        lambda min_pol=None, min_gas_units=None: True,
    )

    assert rt.maybe_auto_topup_pol(context="cycle_start") is True
    out = capsys.readouterr().out
    assert "AUTO-POL consider" in out
    assert "target=" in out


def test_stage_snapshot_pol_0_025_needs_topup_before_swap(_stage_gas_knobs):
    """Reproduces stage: MIN_POL=0.005 env but ~0.025 POL cannot afford urgent swap gas."""
    floor = rt._pol_operating_floor(0.005, urgent=True)
    assert floor > 0.025
    assert rt.pol_can_broadcast_tx(gas_units=int(rt.POL_UNWRAP_GAS_UNITS), pol_balance=0.025)


def _mock_w3(*, pol: float, gas_gwei: float = 100.0):
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
            raise AssertionError("unexpected broadcast")

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


def test_ensure_startup_router_approval_skips_when_allowance_sufficient(monkeypatch, capsys):
    monkeypatch.setattr("swap_executor._erc20_allowance", lambda *_a, **_k: 10**30)

    ok = ensure_startup_router_approval(_mock_w3(pol=1.0), "0x" + "11" * 32, "0x" + "ee" * 20)
    assert ok is True
    assert "Skipped — allowance sufficient" in capsys.readouterr().out


def test_ensure_startup_router_approval_skips_without_broadcast_when_pol_too_low(monkeypatch, capsys):
    monkeypatch.setattr("swap_executor._erc20_allowance", lambda *_a, **_k: 0)
    monkeypatch.setattr("swap_executor.cfg.POL_APPROVE_GAS_UNITS", 85_000)

    ok = ensure_startup_router_approval(
        _mock_w3(pol=0.02, gas_gwei=300.0),
        "0x" + "22" * 32,
        "0x" + "ee" * 20,
        force=True,
    )
    assert ok is False
    assert "Skipped — insufficient POL for approve" in capsys.readouterr().out


def test_pol_can_broadcast_tx_for_unwrap_at_stage_pol(monkeypatch):
    monkeypatch.setattr(rt, "POL_UNWRAP_GAS_UNITS", 140_000)
    monkeypatch.setattr(rt.GAS_PROTECTOR, "get_gas_price_gwei", lambda: 120.0)

    assert rt.pol_can_broadcast_tx(gas_units=140_000, pol_balance=0.025) is True
    assert rt.pol_can_broadcast_tx(gas_units=140_000, pol_balance=0.010) is False


def test_pol_operating_floor_beats_stale_env_min(_stage_gas_knobs):
    assert rt._pol_operating_floor(0.005, urgent=True) == pytest.approx(0.0752, rel=1e-3)
