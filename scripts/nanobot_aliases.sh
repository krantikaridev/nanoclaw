#!/usr/bin/env bash
# shellcheck shell=bash
# Usage:
#   source scripts/nanobot_aliases.sh
#   scripts/nanobot_aliases.sh --install
set -euo pipefail

_nanoclaw_resolve_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/.." && pwd
}

NANOCLAW_ROOT="${NANOCLAW_ROOT:-$(_nanoclaw_resolve_root)}"

_nanoclaw_enter_root() {
  cd "${NANOCLAW_ROOT}" || {
    echo "❌ cannot cd to ${NANOCLAW_ROOT}"
    return 1
  }
}

_nanoclaw_activate_venv() {
  if [[ -f "${NANOCLAW_ROOT}/.venv/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "${NANOCLAW_ROOT}/.venv/bin/activate"
  fi
}

nanoup() {
  bash "${NANOCLAW_ROOT}/scripts/nanoup.sh" "$@"
}

nanokill() {
  bash "${NANOCLAW_ROOT}/scripts/nanokill.sh" "$@"
}

nanostatus() {
  _nanoclaw_enter_root || return 1
  _nanoclaw_activate_venv
  python scripts/pnl_report.py
}

nanopnl() {
  nanostatus "$@"
}

nanorestart() {
  nanoup "$@" && nanostatus
}

nanobot() {
  _nanoclaw_enter_root || return 1
  tail -f real_cron.log
}

nanoattach() {
  nanobot "$@"
}

nanoenvsync() {
  _nanoclaw_enter_root || return 1
  _nanoclaw_activate_venv
  python scripts/nanoenv_example.py --write
  python scripts/verify_env_example_keys.py
}

nanoenvcheck() {
  _nanoclaw_enter_root || return 1
  _nanoclaw_activate_venv
  python scripts/verify_env_example_keys.py
}

nanoenvstage() {
  _nanoclaw_enter_root || return 1
  nanoenvsync
  git add .env.example
}

nanocommit() {
  _nanoclaw_enter_root || return 1
  git config core.hooksPath .githooks >/dev/null 2>&1 || true
  git commit "$@"
}

nanopush() {
  _nanoclaw_enter_root || return 1
  _nanoclaw_activate_venv
  git config core.hooksPath .githooks >/dev/null 2>&1 || true
  python scripts/check_committed_secrets.py --all-tracked
  python scripts/nanoenv_example.py --write
  python scripts/verify_env_example_keys.py
  git add .env.example
  git push "$@"
}

_nanoclaw_install_aliases() {
  local bashrc source_line
  bashrc="${HOME}/.bashrc"
  source_line="source \"${NANOCLAW_ROOT}/scripts/nanobot_aliases.sh\""
  if [[ -f "${bashrc}" ]] && grep -F "${source_line}" "${bashrc}" >/dev/null 2>&1; then
    echo "✅ aliases already installed in ${bashrc}"
  else
    printf '\n# nanoclaw aliases\n%s\n' "${source_line}" >> "${bashrc}"
    echo "✅ added alias bootstrap to ${bashrc}"
  fi
  echo "Run: source ~/.bashrc"
  echo "Verify: type nanoup && type nanokill && type nanorestart && type nanostatus"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "${1:-}" == "--install" ]]; then
    _nanoclaw_install_aliases
    exit 0
  fi
  cat <<'EOF'
This script defines nanoclaw shell aliases/functions.

Use one of:
  source scripts/nanobot_aliases.sh
  scripts/nanobot_aliases.sh --install
EOF
fi
