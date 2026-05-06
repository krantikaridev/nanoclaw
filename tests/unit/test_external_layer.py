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
