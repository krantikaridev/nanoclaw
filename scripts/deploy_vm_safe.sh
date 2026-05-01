#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/deploy_vm_safe.sh [branch]
# Example:
#   ./scripts/deploy_vm_safe.sh V2

BRANCH="${1:-V2}"

echo "=== Nanoclaw safe deploy ($(date)) ==="
echo "Branch: ${BRANCH}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ Refusing deploy: working tree is not clean."
  echo "   Commit/stash/discard local edits first."
  exit 1
fi

echo "[1/6] fetch"
git fetch --all --prune

echo "[2/6] checkout branch"
git checkout "${BRANCH}"

echo "[3/6] fast-forward pull"
git pull --ff-only

echo "[4/6] local verification"
python -m compileall -q .
python -m pytest -q

echo "[5/6] restart bot process"
pkill -f clean_swap.py || true
sleep 2
nohup python clean_swap.py > real_cron.log 2>&1 &

echo "[6/6] tail startup logs"
sleep 2
tail -n 30 real_cron.log || true

echo "✅ Safe deploy complete"
