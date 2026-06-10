#!/usr/bin/env bash
# Pre-merge V3 → V2 gate (run on dev machine before nanodeploy to stage VM).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== v3_pre_deploy_check | $(date -u +%Y-%m-%dT%H:%M:%SZ) | $ROOT ==="

HEAD="$(git log -1 --oneline 2>/dev/null || true)"
echo "CHECKLIST git_head: ${HEAD:-unknown}"

# V3 sprint env keys — must appear in .env.example (values may differ on VM).
V3_ENV_KEYS=(
  FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED
  EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED
  PNL_FLOW_AUTO_SYNC_ENABLED
  FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED
  DRAWDOWN_THROTTLE_ENABLED
  ADVERSE_CHURN_GUARD_ENABLED
  MAIN_STRATEGY_HIGH_STABLE_WMATIC_ROTATION_ENABLED
)
MISSING_KEYS=()
for key in "${V3_ENV_KEYS[@]}"; do
  if ! grep -q "^${key}=" .env.example; then
    MISSING_KEYS+=("$key")
  fi
done
if ((${#MISSING_KEYS[@]} > 0)); then
  echo "CHECKLIST v3_env_keys: FAIL (missing in .env.example: ${MISSING_KEYS[*]})"
  exit 1
fi
echo "CHECKLIST v3_env_keys: PASS (${#V3_ENV_KEYS[@]} keys in .env.example)"

echo "--- env.example coverage ---"
python scripts/verify_env_example_keys.py

echo "--- compileall ---"
python -m compileall -q nanoclaw modules scripts external_layer

echo "--- unpause readiness (hard gates) ---"
python scripts/unpause_readiness.py

echo "--- wave 1 regression ---"
python -m pytest tests/unit/test_fe_stable_runway_tiered.py tests/unit/test_fe_stable_runway_derisk.py \
  tests/unit/test_fe_tiered_cooldown.py tests/unit/test_external_auto_pause.py \
  tests/unit/test_pnl_flow_onchain.py tests/unit/test_nano_green.py -q

echo "--- wave 2 regression ---"
python -m pytest tests/unit/test_pnl_report.py tests/unit/test_pnl_adverse_day.py \
  tests/unit/test_fe_dynamic_trim.py tests/unit/test_drawdown_throttle.py \
  tests/unit/test_adverse_churn_guard.py -q

echo "--- wave 3 regression ---"
python -m pytest tests/unit/test_high_stable_wmatic_rotation.py -q

echo "--- core guards ---"
python -m pytest tests/unit/test_attribution.py tests/unit/test_env_sync.py -q

echo "--- TIERED allow regression (runway 12h window) ---"
python -m pytest tests/unit/test_nano_green.py::test_runway_lines_scoped_to_window_with_timestamps -q

echo "--- dry nano_green runway (fixture log) ---"
python - <<'PY'
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.nano_green import _runway_lines

fixture = Path("tests/fixtures/v3_pre_deploy")
now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
lines = _runway_lines(fixture, hours=12.0, n=3, now=now)
stale = [ln for ln in lines if "TIERED | allow" in ln]
if stale:
    print("FAIL | stale TIERED allow in fixture runway tail:")
    for ln in stale:
        print(f"  {ln}")
    raise SystemExit(1)
if not lines:
    raise SystemExit("FAIL | no runway lines in fixture log")
print("PASS | fixture runway lines (no stale TIERED allow):")
for ln in lines:
    print(f"  {ln}")
PY

echo ""
echo "CHECKLIST summary:"
echo "  git_head:     ${HEAD:-unknown}"
echo "  v3_env_keys:  PASS"
echo "  tiered_allow: PASS (pytest + fixture dry)"
echo ""
echo "=== v3_pre_deploy_check: PASS ==="
