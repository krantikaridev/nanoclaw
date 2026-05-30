#!/usr/bin/env bash
# Portfolio green gate — configurable window (default 12h from env).
# Usage: nanogreen | nanogreen --hours 8 | nanogreen --hours 24 --session-min-pct -1
set -euo pipefail

ROOT="${NANOCLAW_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "${ROOT}" || exit 1

if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

PYTHON="python3"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

exec "${PYTHON}" scripts/nano_green.py "$@"
