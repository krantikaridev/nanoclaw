#!/usr/bin/env bash
# Remote nanoclaw ops via SSH — laptop → VM (replaces ssh + cd + activate dance).
#
# Usage:
#   ./scripts/nanoremote.sh --role stage logs
#   ./scripts/nanoremote.sh --host 92.4.73.239 --key ~/.ssh/key.pem nano12h
#   ./scripts/nanoremote.sh diag
#   ./scripts/nanoremote.sh shell
#
# Config (optional): ~/.nanoclaw/config.yaml — see infra/config.yaml.example
set -euo pipefail

_nanoremote_self="${BASH_SOURCE[0]}"
if [[ -f "${_nanoremote_self}" ]] && grep -q $'\r' "${_nanoremote_self}" 2>/dev/null; then
  sed -i 's/\r$//' "${_nanoremote_self}"
  exec bash "${_nanoremote_self}" "$@"
fi
unset _nanoremote_self

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEFAULT_CONFIG="${NANOCLAW_OPERATOR_CONFIG:-${HOME}/.nanoclaw/config.yaml}"
DEFAULT_REMOTE_ROOT="${NANOCLAW_REMOTE_ROOT:-${HOME}/.nanobot/workspace/nanoclaw}"
DEFAULT_SSH_USER="${NANOCLAW_SSH_USER:-ubuntu}"

CONFIG_PATH="${DEFAULT_CONFIG}"
SSH_USER="${DEFAULT_SSH_USER}"
SSH_KEY=""
SSH_HOST=""
ROLE=""
REMOTE_ROOT="${DEFAULT_REMOTE_ROOT}"
COMMAND=""
LOG_LINES=50
LOG_FOLLOW=0
DRY_RUN=0

_nanoremote_usage() {
  cat <<'EOF'
Usage: nanoremote.sh [options] <command>

Commands:
  logs      Tail real_cron.log (default: last 50 lines; --follow for -f)
  nano8h    Run 8h portfolio green gate on remote VM
  nano12h   Run 12h portfolio green gate on remote VM
  diag      Run nanodiag leave monitor on remote VM
  shell     Interactive SSH session (cd repo + activate venv)

Options:
  --config PATH   Operator config (default: ~/.nanoclaw/config.yaml)
  --role ROLE     stage | dev — pick host from config
  --host HOST     VM IP or hostname (overrides --role)
  --user USER     SSH user (default: ubuntu)
  --key PATH      SSH private key (default: ssh_key from config)
  --remote PATH   Remote repo root (default: ~/.nanobot/workspace/nanoclaw)
  --lines N       Lines for logs (default: 50)
  --follow        tail -f real_cron.log (implies -t for SSH)
  --dry-run       Print remote script without SSH (for tests / debugging)

Examples:
  ./scripts/nanoremote.sh --role stage logs
  ./scripts/nanoremote.sh --host 92.4.73.239 --key ~/.ssh/key.pem nano12h
  ./scripts/nanoremote.sh --role dev --follow logs
EOF
}

_nanoremote_read_yaml_value() {
  local key="$1"
  local file="$2"
  if [[ ! -f "${file}" ]]; then
    return 1
  fi
  local line
  line="$(grep -E "^[[:space:]]*${key}:[[:space:]]*" "${file}" | head -1 || true)"
  if [[ -z "${line}" ]]; then
    return 1
  fi
  local value="${line#*:}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  if [[ -z "${value}" ]]; then
    return 1
  fi
  printf '%s' "${value}"
}

_nanoremote_load_config() {
  if [[ ! -f "${CONFIG_PATH}" ]]; then
    return 0
  fi
  if [[ -z "${SSH_KEY}" ]]; then
    SSH_KEY="$(_nanoremote_read_yaml_value ssh_key "${CONFIG_PATH}" 2>/dev/null || true)"
  fi
  local cfg_user
  cfg_user="$(_nanoremote_read_yaml_value ssh_user "${CONFIG_PATH}" 2>/dev/null || true)"
  if [[ -n "${cfg_user}" && "${SSH_USER}" == "${DEFAULT_SSH_USER}" ]]; then
    SSH_USER="${cfg_user}"
  fi
  local cfg_root
  cfg_root="$(_nanoremote_read_yaml_value remote_root "${CONFIG_PATH}" 2>/dev/null || true)"
  if [[ -n "${cfg_root}" && "${REMOTE_ROOT}" == "${DEFAULT_REMOTE_ROOT}" ]]; then
    REMOTE_ROOT="${cfg_root}"
  fi
}

_nanoremote_resolve_host() {
  if [[ -n "${SSH_HOST}" ]]; then
    return 0
  fi
  if [[ -z "${ROLE}" && -f "${CONFIG_PATH}" ]]; then
    ROLE="stage"
  fi
  case "${ROLE}" in
    stage)
      SSH_HOST="$(_nanoremote_read_yaml_value stage_host "${CONFIG_PATH}" 2>/dev/null || true)"
      ;;
    dev)
      SSH_HOST="$(_nanoremote_read_yaml_value dev_host "${CONFIG_PATH}" 2>/dev/null || true)"
      ;;
    "")
      ;;
    *)
      echo "❌ nanoremote: unknown --role '${ROLE}' (use stage or dev)"
      exit 1
      ;;
  esac
}

_nanoremote_parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config)
        CONFIG_PATH="$2"
        shift 2
        ;;
      --role)
        ROLE="$2"
        shift 2
        ;;
      --host)
        SSH_HOST="$2"
        shift 2
        ;;
      --user)
        SSH_USER="$2"
        shift 2
        ;;
      --key)
        SSH_KEY="$2"
        shift 2
        ;;
      --remote)
        REMOTE_ROOT="$2"
        shift 2
        ;;
      --lines)
        LOG_LINES="$2"
        shift 2
        ;;
      --follow)
        LOG_FOLLOW=1
        shift
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h | --help)
        _nanoremote_usage
        exit 0
        ;;
      logs | nano8h | nano12h | diag | shell)
        if [[ -n "${COMMAND}" ]]; then
          echo "❌ nanoremote: only one command allowed (got '${COMMAND}' and '$1')"
          exit 1
        fi
        COMMAND="$1"
        shift
        ;;
      *)
        echo "❌ nanoremote: unknown argument '$1'"
        _nanoremote_usage
        exit 1
        ;;
    esac
  done
}

_nanoremote_remote_prelude() {
  cat <<EOF
set -euo pipefail
cd '${REMOTE_ROOT}' || { echo "❌ cannot cd to ${REMOTE_ROOT}"; exit 1; }
if [[ ! -f clean_swap.py ]]; then
  echo "❌ clean_swap.py missing in ${REMOTE_ROOT}"
  exit 1
fi
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
EOF
}

_nanoremote_run_remote() {
  local remote_script="$1"
  local use_tty="${2:-0}"
  local -a ssh_args=(ssh -o BatchMode=yes -o ConnectTimeout=15)
  if [[ -n "${SSH_KEY}" ]]; then
    local expanded_key="${SSH_KEY/#\~/${HOME}}"
    if [[ ! -f "${expanded_key}" ]]; then
      echo "❌ nanoremote: SSH key not found: ${expanded_key}"
      exit 1
    fi
    ssh_args+=(-i "${expanded_key}")
  fi
  if [[ "${use_tty}" -eq 1 ]]; then
    ssh_args+=(-t)
  fi
  ssh_args+=("${SSH_USER}@${SSH_HOST}" bash -s)
  printf '%s\n' "${remote_script}" | "${ssh_args[@]}"
}

_nanoremote_validate() {
  if [[ -z "${COMMAND}" ]]; then
    echo "❌ nanoremote: missing command"
    _nanoremote_usage
    exit 1
  fi
  _nanoremote_load_config
  _nanoremote_resolve_host
  if [[ -z "${SSH_HOST}" ]]; then
    echo "❌ nanoremote: no host — use --host, --role stage|dev, or set stage_host in ${CONFIG_PATH}"
    exit 1
  fi
}

_nanoremote_dispatch() {
  local prelude remote_script use_tty=0
  prelude="$(_nanoremote_remote_prelude)"

  case "${COMMAND}" in
    logs)
      if [[ "${LOG_FOLLOW}" -eq 1 ]]; then
        use_tty=1
        remote_script="${prelude}
tail -f real_cron.log"
      else
        remote_script="${prelude}
tail -n ${LOG_LINES} real_cron.log"
      fi
      ;;
    nano8h)
      remote_script="${prelude}
bash scripts/nano_green.sh --hours 8"
      ;;
    nano12h)
      remote_script="${prelude}
bash scripts/nano_green.sh --hours 12"
      ;;
    diag)
      remote_script="${prelude}
bash scripts/nanodiag.sh"
      ;;
    shell)
      use_tty=1
      remote_script="${prelude}
echo \"=== nanoremote shell | \$(date -u +%Y-%m-%dT%H:%M:%SZ) | ${REMOTE_ROOT} ===\"
exec bash -l"
      ;;
    *)
      echo "❌ nanoremote: unknown command '${COMMAND}'"
      exit 1
      ;;
  esac

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '%s\n' "${remote_script}"
    return 0
  fi
  _nanoremote_run_remote "${remote_script}" "${use_tty}"
}

_nanoremote_parse_args "$@"
_nanoremote_validate
_nanoremote_dispatch
