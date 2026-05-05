#!/usr/bin/env bash
set -euo pipefail

ROOT="${NANOCLAW_ROOT:-$HOME/.nanobot/workspace/nanoclaw}"
cd "${ROOT}" || {
  echo "❌ nanorestart: cannot cd to ${ROOT}"
  exit 1
}

bash "${ROOT}/scripts/nanoup.sh" "$@"
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
fi

echo "🩺 nanohealth: Polygon RPC check"
python scripts/nanohealth.py || echo "⚠️ nanorestart: nanohealth failed — PnL below may be misleading until RPC is fixed"

python scripts/pnl_report.py "$@"
