import importlib.util
import inspect
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
    risk_checker._RECENT_PROTECTION_EVALS.clear()
    risk_checker._FORCE_MIN_UNTIL_TS = 0.0
    yield
    control._last_successful_risk = None
    risk_checker._RECENT_PROTECTION_EVALS.clear()
    risk_checker._FORCE_MIN_UNTIL_TS = 0.0


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
    out = risk_checker.evaluate_risk()
    assert out["paused"] is False
    assert out["max_copy_trade_pct"] == 0.06
    assert out["usdt_balance"] == 100.0
    assert out["wmatic_balance"] == 100.0
    assert "Healthy balance" in str(out.get("reason", ""))


def test_evaluate_risk_low_usdt():
    out = risk_checker.evaluate_risk(usdt_balance=59.0, wmatic_balance=100.0)
    assert out["paused"] is True
    assert out["max_copy_trade_pct"] == 0.02
    assert out["usdt_balance"] == 59.0
    assert out["wmatic_balance"] == 100.0
    assert "Critical low balance" in str(out.get("reason", ""))


def test_evaluate_risk_low_wmatic():
    out = risk_checker.evaluate_risk(usdt_balance=100.0, wmatic_balance=49.0)
    assert out["paused"] is True
    assert out["max_copy_trade_pct"] == 0.02
    assert out["usdt_balance"] == 100.0
    assert out["wmatic_balance"] == 49.0


def test_evaluate_risk_at_critical_floor_is_moderate_not_critical():
    """Exactly 60 USDT / 50 WMATIC clears the critical tier (not <)."""
    out = risk_checker.evaluate_risk(usdt_balance=60.0, wmatic_balance=50.0)
    assert out["paused"] is False
    assert out["max_copy_trade_pct"] == 0.03
    assert out["usdt_balance"] == 60.0
    assert out["wmatic_balance"] == 50.0
    assert "Moderate low balance" in str(out.get("reason", ""))


def test_evaluate_risk_moderate_tier():
    out = risk_checker.evaluate_risk(usdt_balance=84.0, wmatic_balance=100.0)
    assert out["paused"] is False
    assert out["max_copy_trade_pct"] == 0.03


def test_evaluate_risk_full_health_threshold():
    """At least 85 USDT and 65 WMATIC → top tier."""
    out = risk_checker.evaluate_risk(usdt_balance=85.0, wmatic_balance=65.0)
    assert out["paused"] is False
    assert out["max_copy_trade_pct"] == 0.06


def test_evaluate_risk_recent_streak_forces_min_for_10_minutes(monkeypatch):
    t = {"now": 1_000_000.0}

    def fake_time():
        return t["now"]

    monkeypatch.setattr(risk_checker.time, "time", fake_time)

    # Three consecutive protected evaluations (critical/moderate) triggers clamp.
    out1 = risk_checker.evaluate_risk(usdt_balance=59.0, wmatic_balance=100.0)  # critical
    assert out1["max_copy_trade_pct"] == 0.02
    t["now"] += 1

    out2 = risk_checker.evaluate_risk(usdt_balance=84.0, wmatic_balance=100.0)  # moderate
    assert out2["max_copy_trade_pct"] == 0.03
    t["now"] += 1

    out3 = risk_checker.evaluate_risk(usdt_balance=100.0, wmatic_balance=64.0)  # moderate
    assert out3["max_copy_trade_pct"] == 0.02
    t["now"] += 1

    # Even if balances recover, clamp should apply for the next 10 minutes.
    healthy = risk_checker.evaluate_risk(usdt_balance=1_000.0, wmatic_balance=1_000.0)
    assert healthy["paused"] is False
    assert healthy["max_copy_trade_pct"] == 0.02

    # After 10 minutes, healthy should return to normal 6% cap.
    t["now"] += 10 * 60 + 1
    recovered = risk_checker.evaluate_risk(usdt_balance=1_000.0, wmatic_balance=1_000.0)
    assert recovered["paused"] is False
    assert recovered["max_copy_trade_pct"] == 0.06


def test_run_control_loop_default_interval_30s():
    sig = inspect.signature(control._run_control_loop)
    assert sig.parameters["interval_seconds"].default == 30.0


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
            "max_copy_trade_pct": 0.02,
            "reason": "Critical low balance (test)",
            "usdt_balance": 1.0,
            "wmatic_balance": 1.0,
        }

    monkeypatch.setattr(control, "evaluate_risk", fake_evaluate_risk)
    risk_back = control.update_control()
    assert risk_back["paused"] is True
    assert risk_back["reason"] == "Critical low balance (test)"

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["paused"] is True
    assert written["reason"] == "Critical low balance (test)"
    assert written["usdt_balance"] == 1.0
    assert written["wmatic_balance"] == 1.0
    assert written["max_copy_trade_pct"] == 0.02
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


def test_load_cycle_control_reads_reason(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(
        '{"paused": false, "max_copy_trade_pct": 0.04, "reason": "Moderate balance"}',
        encoding="utf-8",
    )
    snap = control.load_cycle_control(p)
    assert snap.reason == "Moderate balance"


def test_update_control_survives_evaluate_failure_without_prior_snapshot(
    tmp_path: Path, monkeypatch, capsys
):
    out_path = tmp_path / "missing.json"
    monkeypatch.setattr(control, "CONTROL_JSON_PATH", out_path)
    monkeypatch.setattr(
        control,
        "evaluate_risk",
        lambda: (_ for _ in ()).throw(RuntimeError("RPC unavailable")),
    )
    out = control.update_control()
    assert out["paused"] is False
    assert out["max_copy_trade_pct"] == 0.08
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert out_path.exists()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["paused"] is False
    assert written["last_updated"].endswith("Z")


def test_update_control_failure_heartbeat_preserves_existing_reason(
    tmp_path: Path, monkeypatch
):
    out_path = tmp_path / "control.json"
    out_path.write_text(
        '{"paused": true, "reason": "Low balance protection", "max_copy_trade_pct": 0.08, '
        '"usdt_balance": 12.5, "wmatic_balance": 3.25}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(control, "CONTROL_JSON_PATH", out_path)
    monkeypatch.setattr(
        control,
        "evaluate_risk",
        lambda: (_ for _ in ()).throw(RuntimeError("RPC unavailable")),
    )
    control.update_control()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["paused"] is True
    assert written["reason"] == "Low balance protection"
    assert written["usdt_balance"] == 12.5
    assert written["wmatic_balance"] == 3.25
    assert written["last_updated"].endswith("Z")


def test_update_control_failure_reuses_last_good_state(tmp_path: Path, monkeypatch, capsys):
    out_path = tmp_path / "control.json"
    monkeypatch.setattr(control, "CONTROL_JSON_PATH", out_path)

    calls = {"n": 0}

    def flaky_evaluate_risk():
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "paused": True,
                "max_copy_trade_pct": 0.02,
                "reason": "Critical low balance (test)",
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
    assert written["reason"] == "Critical low balance (test)"
    assert written["usdt_balance"] == 10.0
    assert written["wmatic_balance"] == 10.0

    captured = capsys.readouterr()
    assert "WARNING" in captured.out
