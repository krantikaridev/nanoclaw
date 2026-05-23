"""Runtime state paths excluded from deploy tooling."""

from nanoclaw.runtime_state import CONTROL_JSON_FILENAME, NANOUP_PRESERVE_RUNTIME_FILES


def test_control_json_listed_for_nanoup_preservation():
    assert CONTROL_JSON_FILENAME == "control.json"
    assert CONTROL_JSON_FILENAME in NANOUP_PRESERVE_RUNTIME_FILES
