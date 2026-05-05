#!/usr/bin/env bash
# shellcheck shell=bash
# Usage:
#   source scripts/nanobot_aliases.sh
#   scripts/nanobot_aliases.sh --install
_NANOCLAW_ALIASES_SOURCED=0
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  _NANOCLAW_ALIASES_SOURCED=1
  # Keep strict checks active while loading definitions, then restore caller shell flags.
  _NANOCLAW_ALIASES_SAVED_SET_OPTS="$(set +o)"
fi
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
  python scripts/pnl_report.py "$@"
}

nanopnl() {
  nanostatus "$@"
}

nanorestart() {
  nanoup "$@" && nanostatus "$@"
}

nanodaily() {
  _nanoclaw_enter_root || return 1
  if [[ -x "${NANOCLAW_ROOT}/nanodaily" ]]; then
    bash "${NANOCLAW_ROOT}/nanodaily"
  else
    echo "❌ nanodaily script missing or not executable: ${NANOCLAW_ROOT}/nanodaily"
    return 1
  fi
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
}

_nanoclaw_install_cmd_shims() {
  local bindir
  bindir="${HOME}/.local/bin"
  mkdir -p "${bindir}"

  cat >"${bindir}/nanoup" <<EOF
#!/usr/bin/env bash
set -euo pipefail
bash "${NANOCLAW_ROOT}/scripts/nanoup.sh" "\$@"
EOF
  cat >"${bindir}/nanokill" <<EOF
#!/usr/bin/env bash
set -euo pipefail
bash "${NANOCLAW_ROOT}/scripts/nanokill.sh" "\$@"
EOF
  cat >"${bindir}/nanorestart" <<EOF
#!/usr/bin/env bash
set -euo pipefail
bash "${NANOCLAW_ROOT}/scripts/nanorestart.sh" "\$@"
EOF
  cat >"${bindir}/nanostatus" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "${NANOCLAW_ROOT}"
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
fi
python scripts/pnl_report.py "\$@"
EOF
  cat >"${bindir}/nanopnl" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "${bindir}/nanostatus" "\$@"
EOF
  cat >"${bindir}/nanobot" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "${NANOCLAW_ROOT}"
tail -f real_cron.log
EOF
  cat >"${bindir}/nanoattach" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "${bindir}/nanobot" "\$@"
EOF
  cat >"${bindir}/nanodaily" <<EOF
#!/usr/bin/env bash
set -euo pipefail
bash "${NANOCLAW_ROOT}/nanodaily" "\$@"
EOF
  chmod +x \
    "${bindir}/nanoup" \
    "${bindir}/nanokill" \
    "${bindir}/nanorestart" \
    "${bindir}/nanostatus" \
    "${bindir}/nanopnl" \
    "${bindir}/nanobot" \
    "${bindir}/nanoattach" \
    "${bindir}/nanodaily"

  if [[ -f "${HOME}/.bashrc" ]] && ! grep -F 'export PATH="$HOME/.local/bin:$PATH"' "${HOME}/.bashrc" >/dev/null 2>&1; then
    printf '\n# local user bin for nanoclaw command shims\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "${HOME}/.bashrc"
    echo "✅ added ~/.local/bin PATH bootstrap to ${HOME}/.bashrc"
  fi
  echo "✅ installed standalone nano* command shims in ${bindir}"
  echo "Verify: command -v nanoup nanostatus nanopnl nanodaily"
}

_nanoclaw_install_everything() {
  _nanoclaw_install_aliases
  _nanoclaw_install_cmd_shims
  echo "Run: source ~/.bashrc"
  echo "Verify: type nanoup && type nanokill && type nanorestart && type nanostatus && type nanodaily"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "${1:-}" == "--install" ]]; then
    _nanoclaw_install_everything
    exit 0
  fi
  cat <<'EOF'
This script defines nanoclaw shell aliases/functions.

Use one of:
  source scripts/nanobot_aliases.sh
  scripts/nanobot_aliases.sh --install
EOF
fi

if [[ "${_NANOCLAW_ALIASES_SOURCED}" -eq 1 ]]; then
  # Restore caller shell options to avoid mutating interactive behavior after `source`.
  eval "${_NANOCLAW_ALIASES_SAVED_SET_OPTS}"
  unset _NANOCLAW_ALIASES_SAVED_SET_OPTS
fi
unset _NANOCLAW_ALIASES_SOURCED
