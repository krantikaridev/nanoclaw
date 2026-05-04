#!/usr/bin/env bash
set -euo pipefail

ROOT="${NANOCLAW_ROOT:-$HOME/.nanobot/workspace/nanoclaw}"
cd "${ROOT}" || {
  echo "❌ nanokill: cannot cd to ${ROOT}"
  exit 1
}

if pgrep -f "clean_swap.py" >/dev/null 2>&1; then
  pkill -f "clean_swap.py" || true
  sleep 1
fi

if pgrep -f "clean_swap.py" >/dev/null 2>&1; then
  echo "⚠️ nanokill: clean_swap.py still running"
  pgrep -af "clean_swap.py" || true
  exit 1
fi

echo "✅ nanokill: bot process stopped"
