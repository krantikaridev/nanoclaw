import json
from pathlib import Path

from external_layer import control
from external_layer import risk_checker


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
