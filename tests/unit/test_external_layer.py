import importlib.util
import json
import sys
from pathlib import Path

import pytest

from external_layer import control
from external_layer import risk_checker


@pytest.fixture(autouse=True)
def _reset_control_last_successful_risk():
    """Isolate module-level cache between tests."""
    control._last_successful_risk = None
    yield
    control._last_successful_risk = None


def test_control_command_defaults():
    cmd = control.ControlCommand(last_updated="2026-05-06T00:00:00Z")
    assert cmd.paused is False
    assert cmd.max_copy_trade_pct == 0.08
    assert cmd.force_defensive is False
    assert cmd.last_updated == "2026-05-06T00:00:00Z"


def test_control_command_to_dict():
    cmd = control.ControlCommand(
        paused=True,
        max_copy_trade_pct=0.1,
        force_defensive=True,
        last_updated="x",
    )
    assert cmd.to_dict() == {
        "paused": True,
        "max_copy_trade_pct": 0.1,
        "force_defensive": True,
        "last_updated": "x",
    }


def test_write_control_writes_project_json(tmp_path: Path, monkeypatch):
    out = tmp_path / "control.json"
    monkeypatch.setattr(control, "CONTROL_JSON_PATH", out)
    payload = {
        "paused": False,
        "max_copy_trade_pct": 0.08,
        "force_defensive": False,
        "last_updated": "2026-05-06T12:00:00Z",
    }
    control.write_control(payload)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == payload


def test_risk_checker_skeleton():
    assert risk_checker.get_current_risk_state() == "MEDIUM"
    assert risk_checker.should_pause() is False
    assert risk_checker.get_recommended_max_size() == 0.08


def test_evaluate_risk_healthy_balances(monkeypatch):
    monkeypatch.setattr(risk_checker, "get_wallet_balances", lambda: (100.0, 100.0))
    assert risk_checker.evaluate_risk() == {
        "paused": False,
        "usdt_balance": 100.0,
        "wmatic_balance": 100.0,
    }


def test_evaluate_risk_low_usdt():
    assert risk_checker.evaluate_risk(usdt_balance=49.0, wmatic_balance=100.0) == {
        "paused": True,
        "reason": "Low balance protection",
        "usdt_balance": 49.0,
        "wmatic_balance": 100.0,
    }


def test_evaluate_risk_low_wmatic():
    assert risk_checker.evaluate_risk(usdt_balance=100.0, wmatic_balance=39.0) == {
        "paused": True,
        "reason": "Low balance protection",
        "usdt_balance": 100.0,
        "wmatic_balance": 39.0,
    }


def test_evaluate_risk_threshold_at_minimum_not_paused():
    """Exactly at thresholds should not pause (strictly less than)."""
    assert risk_checker.evaluate_risk(usdt_balance=50.0, wmatic_balance=40.0) == {
        "paused": False,
        "usdt_balance": 50.0,
        "wmatic_balance": 40.0,
    }


def test_control_py_imports_when_loaded_as_filepath():
    """Same entrypoint as ``python external_layer/control.py`` — no ``__package__``."""
    root = Path(__file__).resolve().parents[2]
    path = root / "external_layer" / "control.py"
    name = "_nanoclaw_ext_control_standalone"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
        assert hasattr(mod, "update_control")
        assert hasattr(mod, "_run_control_loop")
    finally:
        sys.modules.pop(name, None)


def test_update_control_writes_json_from_evaluate_risk(tmp_path: Path, monkeypatch):
    out = tmp_path / "control.json"
    monkeypatch.setattr(control, "CONTROL_JSON_PATH", out)

    def fake_evaluate_risk():
        return {
            "paused": True,
            "reason": "Low balance protection",
            "usdt_balance": 1.0,
            "wmatic_balance": 1.0,
        }

    monkeypatch.setattr(control, "evaluate_risk", fake_evaluate_risk)
    risk_back = control.update_control()
    assert risk_back["paused"] is True
    assert risk_back["reason"] == "Low balance protection"

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["paused"] is True
    assert written["reason"] == "Low balance protection"
    assert written["max_copy_trade_pct"] == 0.08
    assert written["force_defensive"] is False
    assert written["last_updated"].endswith("Z")


def test_load_cycle_control_missing_invalid_and_ok(tmp_path):
    missing = tmp_path / "nope.json"
    assert control.load_cycle_control(missing) == control.CycleControlSnapshot()

    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert control.load_cycle_control(bad) == control.CycleControlSnapshot()

    ok = tmp_path / "ok.json"
    ok.write_text(
        '{"paused": true, "max_copy_trade_pct": 0.1, "force_defensive": false}',
        encoding="utf-8",
    )
    snap = control.load_cycle_control(ok)
    assert snap.paused is True
    assert snap.max_copy_trade_pct == 0.1
    assert snap.force_defensive is False


def test_load_cycle_control_rejects_bad_max_pct(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"max_copy_trade_pct": "not-a-number"}', encoding="utf-8")
    snap = control.load_cycle_control(p)
    assert snap.max_copy_trade_pct is None


def test_load_cycle_control_empty_file_defaults(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    assert control.load_cycle_control(p) == control.CycleControlSnapshot()


def test_update_control_survives_evaluate_failure_without_prior_snapshot(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.setattr(control, "CONTROL_JSON_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(
        control,
        "evaluate_risk",
        lambda: (_ for _ in ()).throw(RuntimeError("RPC unavailable")),
    )
    out = control.update_control()
    assert out == {"paused": False}
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert not (tmp_path / "missing.json").exists()


def test_update_control_failure_reuses_last_good_state(tmp_path: Path, monkeypatch, capsys):
    out_path = tmp_path / "control.json"
    monkeypatch.setattr(control, "CONTROL_JSON_PATH", out_path)

    calls = {"n": 0}

    def flaky_evaluate_risk():
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "paused": True,
                "reason": "Low balance protection",
                "usdt_balance": 10.0,
                "wmatic_balance": 10.0,
            }
        raise RuntimeError("RPC down")

    monkeypatch.setattr(control, "evaluate_risk", flaky_evaluate_risk)

    first = control.update_control()
    assert first["paused"] is True

    second = control.update_control()
    assert second["paused"] is True
    assert second["usdt_balance"] == 10.0

    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["paused"] is True
    assert written["reason"] == "Low balance protection"

    captured = capsys.readouterr()
    assert "WARNING" in captured.out
