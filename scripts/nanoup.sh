#!/usr/bin/env bash
# Safe pull + bot restart. FIXED 2026-05-03: resolve repo via env or default nanobot layout.
# Add to ~/.bashrc (bulletproof one-liner):
#   nanoup() { bash "${NANOCLAW_ROOT:-$HOME/.nanobot/workspace/nanoclaw}/scripts/nanoup.sh" "$@"; }
set -euo pipefail

ROOT="${NANOCLAW_ROOT:-$HOME/.nanobot/workspace/nanoclaw}"
cd "${ROOT}" || {
  echo "❌ nanoup: cannot cd to ${ROOT} (set NANOCLAW_ROOT to your nanoclaw checkout)"
  exit 1
}

if [[ ! -f "clean_swap.py" ]]; then
  echo "❌ nanoup: clean_swap.py missing in ${ROOT}"
  exit 1
fi

# Prefer project venv when present
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
fi

echo "=== nanoup | $(date -u +%Y-%m-%dT%H:%M:%SZ) | ${ROOT} ==="

if command -v nanokill >/dev/null 2>&1; then
  nanokill || true
else
  pkill -f "clean_swap.py" 2>/dev/null || true
  sleep 1
fi

BRANCH="${NANOCLAW_BRANCH:-V2}"
git fetch origin "${BRANCH}" 2>/dev/null || git fetch --all --prune
git pull --ff-only "origin" "${BRANCH}" || {
  echo "❌ nanoup: git pull failed — resolve conflicts manually"
  exit 1
}

nohup python clean_swap.py >>real_cron.log 2>&1 &
echo "✅ nanoup: bot started (tail -f real_cron.log)"
sleep 1
tail -n 15 real_cron.log 2>/dev/null || true
