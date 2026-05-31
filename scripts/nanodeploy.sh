#!/usr/bin/env bash
# One-shot VM deploy + post-merge verification (Grok F + freeze lift playbook in code).
#
# Usage (VM):
#   cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate && nanodeploy
#   nanodeploy --skip-nanoup    # verify only (no git pull / restart)
#
# Exit: 0 when nanoup (if run) succeeds AND unpause_readiness hard gates pass.
set -euo pipefail

ROOT="${NANOCLAW_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "${ROOT}" || {
  echo "nanodeploy: cannot cd to ${ROOT}" >&2
  exit 1
}

if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

PYTHON="python3"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

SKIP_NANOUP=0
NANOUP_ARGS=()
for arg in "$@"; do
  if [[ "${arg}" == "--skip-nanoup" ]]; then
    SKIP_NANOUP=1
  else
    NANOUP_ARGS+=("${arg}")
  fi
done

echo "=== nanodeploy | $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC | ${ROOT} ==="

if [[ "${SKIP_NANOUP}" -eq 0 ]]; then
  echo ""
  echo "--- nanoup (pull + preserve control.json + restart) ---"
  bash "${ROOT}/scripts/nanoup.sh" "${NANOUP_ARGS[@]}"
else
  echo ""
  echo "--- skip nanoup (--skip-nanoup) ---"
fi

echo ""
echo "--- shell shims (~/.local/bin; drops legacy bashrc source) ---"
bash "${ROOT}/scripts/nanobot_aliases.sh" --install || echo "WARN nanobot_aliases --install failed"

echo ""
echo "--- rpc_probe (per-endpoint; exit 0 if any healthy) ---"
"${PYTHON}" scripts/rpc_probe.py || echo "WARN rpc_probe: all endpoints failed"

echo ""
echo "--- nanohealth ---"
"${PYTHON}" scripts/nanohealth.py || echo "WARN nanohealth failed"

echo ""
echo "--- unpause_readiness (hard gates) ---"
READINESS_RC=0
"${PYTHON}" scripts/unpause_readiness.py || READINESS_RC=$?

echo ""
echo "--- nanodiag ---"
bash "${ROOT}/scripts/nanodiag.sh" || true

echo ""
echo "--- nano_48h_green (session + pause discipline) ---"
GREEN_RC=0
bash "${ROOT}/scripts/nano_green.sh" || GREEN_RC=$?

echo ""
echo "=== nanodeploy summary ==="
echo "  unpause_readiness: exit ${READINESS_RC} (0=hard gates pass)"
echo "  nano_48h_green:    exit ${GREEN_RC} (0=session≥0 & no fill while paused)"
if [[ "${READINESS_RC}" -ne 0 ]]; then
  echo "  action: fix FAIL lines above before setting control.json paused=false"
else
  echo "  action: hard gates OK — unpause only when you accept session/48h metrics"
fi

exit "${READINESS_RC}"
