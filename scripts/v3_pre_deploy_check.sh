#!/usr/bin/env bash
# Pre-merge V3 → V2 gate (run on dev machine before nanodeploy to stage VM).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== v3_pre_deploy_check | $(date -u +%Y-%m-%dT%H:%M:%SZ) | $ROOT ==="

HEAD="$(git log -1 --oneline 2>/dev/null || true)"
echo "git: ${HEAD:-unknown}"

echo "--- compileall ---"
python -m compileall -q nanoclaw modules scripts external_layer

echo "--- wave 1 regression ---"
python -m pytest tests/unit/test_fe_tiered_cooldown.py tests/unit/test_external_auto_pause.py \
  tests/unit/test_pnl_flow_onchain.py tests/unit/test_nano_green.py -q

echo "--- wave 2 regression ---"
python -m pytest tests/unit/test_fe_dynamic_trim.py tests/unit/test_drawdown_throttle.py \
  tests/unit/test_adverse_churn_guard.py tests/unit/test_fe_stable_runway_derisk.py \
  tests/unit/test_fe_stable_runway_tiered.py -q

echo "--- wave 3 regression ---"
python -m pytest tests/unit/test_high_stable_wmatic_rotation.py -q

echo "--- core guards ---"
python -m pytest tests/unit/test_attribution.py tests/unit/test_env_sync.py -q

echo "=== v3_pre_deploy_check: PASS ==="
