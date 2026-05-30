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

# control.json is operator runtime state (paused, copy caps). Never delete/reset via git or env sync.
# Persistent snapshot: .runtime/control.json.bak (see nanoclaw/runtime_state.py).
_preserve_runtime_state_before_git() {
  if [[ -f scripts/preserve_runtime_state.py ]]; then
    python scripts/preserve_runtime_state.py before-git || true
  fi
}
_preserve_runtime_state_after_git() {
  if [[ -f scripts/preserve_runtime_state.py ]]; then
    python scripts/preserve_runtime_state.py after-git || true
  fi
}
trap _preserve_runtime_state_after_git EXIT

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

# Enforce repo hook path so guarded pre-commit/pre-push checks run even
# when operators use raw git commands on the VM.
git config core.hooksPath .githooks >/dev/null 2>&1 || true

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [[ -z "${CURRENT_BRANCH}" || "${CURRENT_BRANCH}" == "HEAD" ]]; then
  echo "❌ nanoup: detached HEAD detected; checkout a branch before running nanoup"
  exit 1
fi

BRANCH="${NANOCLAW_BRANCH:-${CURRENT_BRANCH}}"
AUTOSTASH="${NANOUP_AUTOSTASH:-0}"
STASH_NAME=""
DID_STASH=0

_preserve_runtime_state_before_git

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  if [[ "${AUTOSTASH}" == "1" ]]; then
    STASH_NAME="nanoup-auto-stash-$(date -u +%Y%m%dT%H%M%SZ)"
    echo "⚠️ nanoup: local changes detected; auto-stashing as '${STASH_NAME}'"
    # Exclude control.json: operator pause/unpause must survive stash/pop cycles.
    git stash push -m "${STASH_NAME}" -- . \
      ':(exclude)control.json' \
      ':(exclude)trade_exits.json' \
      ':(exclude).runtime' \
      ':(exclude).env' \
      >/dev/null 2>&1 || {
      echo "⚠️ nanoup: git stash skipped or empty (continuing)"
    }
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

# Git on Windows dev machines often omits +x on *.sh; legacy wrappers exec scripts directly.
chmod +x scripts/*.sh 2>/dev/null || true

_preserve_runtime_state_after_git

# Keep runtime .env aligned with latest template keys while preserving stage secrets/runtime values.
# Does not touch control.json — operator runtime state only (scripts/preserve_runtime_state.py).
if [[ ! -f "scripts/nanoenv_apply.py" ]]; then
  echo "❌ nanoup: scripts/nanoenv_apply.py missing; cannot safely sync .env from .env.example"
  exit 1
fi
echo "🔄 nanoup: syncing .env from .env.example (preserving secrets/runtime keys)"
python scripts/nanoenv_apply.py --write
MIN_POL_NOW="$(grep -E '^MIN_POL_FOR_GAS=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
if [[ -n "${MIN_POL_NOW}" ]]; then
  echo "✅ nanoup: MIN_POL_FOR_GAS=${MIN_POL_NOW} (from template merge)"
  if awk -v v="${MIN_POL_NOW}" 'BEGIN { exit !(v+0 < 0.12) }'; then
    echo "⚠️ nanoup: MIN_POL_FOR_GAS=${MIN_POL_NOW} is below 0.12 — run: python scripts/nanoenv_apply.py --write"
  fi
else
  echo "⚠️ nanoup: MIN_POL_FOR_GAS not found in .env after sync"
fi

nohup python clean_swap.py >>real_cron.log 2>&1 &
echo "✅ nanoup: bot started (tail -f real_cron.log)"
sleep 1
tail -n 15 real_cron.log 2>/dev/null || true
echo "🩺 nanohealth: Polygon RPC check"
python scripts/nanohealth.py || echo "⚠️ nanoup: nanohealth failed — fix RPC before trusting balances/PnL (docs/readme-vm-update.md)"
