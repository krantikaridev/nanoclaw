"""Tests for V3 pre-deploy gate (scripts/v3_pre_deploy_check.sh helpers)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.nano_green import _runway_lines

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "v3_pre_deploy_check.sh"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "v3_pre_deploy"

V3_SPRINT_ENV_KEYS = (
    "FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED",
    "EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED",
    "PNL_FLOW_AUTO_SYNC_ENABLED",
    "FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED",
    "DRAWDOWN_THROTTLE_ENABLED",
    "ADVERSE_CHURN_GUARD_ENABLED",
    "MAIN_STRATEGY_HIGH_STABLE_WMATIC_ROTATION_ENABLED",
)


def test_v3_pre_deploy_script_exists() -> None:
    assert SCRIPT_PATH.is_file()
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "unpause_readiness.py" in text
    assert "verify_env_example_keys.py" in text
    assert "test_runway_lines_scoped_to_window_with_timestamps" in text


def test_v3_sprint_env_keys_in_env_example() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    present = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", env_example, flags=re.MULTILINE))
    missing = [key for key in V3_SPRINT_ENV_KEYS if key not in present]
    assert not missing, f".env.example missing V3 sprint keys: {missing}"


def test_fixture_runway_excludes_stale_tiered_allow() -> None:
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    lines = _runway_lines(FIXTURE_ROOT, hours=12.0, n=3, now=now)
    assert lines
    assert all("TIERED | allow" not in ln for ln in lines)
    assert any("defer USDC→EQUITY BUY" in ln for ln in lines)
    assert any("TIERED | cooldown" in ln for ln in lines)
