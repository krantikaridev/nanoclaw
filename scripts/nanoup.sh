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

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "❌ nanoup: ${ROOT} is not a git repository"
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [[ -z "${CURRENT_BRANCH}" || "${CURRENT_BRANCH}" == "HEAD" ]]; then
  echo "❌ nanoup: detached HEAD detected; checkout a branch before running nanoup"
  exit 1
fi

BRANCH="${NANOCLAW_BRANCH:-${CURRENT_BRANCH}}"
AUTOSTASH="${NANOUP_AUTOSTASH:-0}"
STASH_NAME=""
DID_STASH=0

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  if [[ "${AUTOSTASH}" == "1" ]]; then
    STASH_NAME="nanoup-auto-stash-$(date -u +%Y%m%dT%H%M%SZ)"
    echo "⚠️ nanoup: local changes detected; auto-stashing as '${STASH_NAME}'"
    git stash push --include-untracked -m "${STASH_NAME}" >/dev/null
    DID_STASH=1
  else
    echo "❌ nanoup: local changes detected. Commit/stash first, or run:"
    echo "   NANOUP_AUTOSTASH=1 nanoup"
    git status --short
    exit 1
  fi
fi

git fetch origin "${BRANCH}" 2>/dev/null || git fetch --all --prune
git pull --ff-only "origin" "${BRANCH}" || {
  if [[ "${DID_STASH}" -eq 1 ]]; then
    echo "⚠️ nanoup: pull failed; your stashed changes are preserved as '${STASH_NAME}'"
  fi
  echo "❌ nanoup: git pull failed — resolve conflicts manually"
  exit 1
}

if [[ "${DID_STASH}" -eq 1 ]]; then
  if ! git stash pop --index >/dev/null; then
    echo "⚠️ nanoup: git pull succeeded but stash apply has conflicts."
    echo "   Resolve conflicts manually; stash entry is preserved if apply failed."
    exit 1
  fi
  echo "✅ nanoup: restored stashed local changes"
fi

nohup python clean_swap.py >>real_cron.log 2>&1 &
echo "✅ nanoup: bot started (tail -f real_cron.log)"
sleep 1
tail -n 15 real_cron.log 2>/dev/null || true
