#!/usr/bin/env bash
set -euo pipefail

source ~/.bashrc 2>/dev/null || true
ROOT="${NANOCLAW_ROOT:-$HOME/.nanobot/workspace/nanoclaw}"
cd "${ROOT}"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
fi

bash "${ROOT}/scripts/nanoup.sh" && python "${ROOT}/scripts/pnl_report.py"
