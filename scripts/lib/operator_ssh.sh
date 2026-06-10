#!/usr/bin/env bash
# Shared SSH/config helpers for operator scripts (nanoremote, dev_*).
# Usage: source "$(dirname "$0")/lib/operator_ssh.sh"  (from scripts/*.sh)
set -euo pipefail

OPERATOR_DEFAULT_CONFIG="${NANOCLAW_OPERATOR_CONFIG:-${HOME}/.nanoclaw/config.yaml}"
OPERATOR_DEFAULT_REMOTE_ROOT="${NANOCLAW_REMOTE_ROOT:-${HOME}/.nanobot/workspace/nanoclaw}"
OPERATOR_DEFAULT_SSH_USER="${NANOCLAW_SSH_USER:-ubuntu}"

operator_read_yaml_value() {
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

operator_expand_path() {
  local p="$1"
  printf '%s' "${p/#\~/${HOME}}"
}

operator_load_ssh_config() {
  local config_path="$1"
  local -n _host="$2"
  local -n _key="$3"
  local -n _user="$4"
  local -n _remote="$5"
  local role="${6:-}"

  if [[ -f "${config_path}" ]]; then
    if [[ -z "${_key}" ]]; then
      _key="$(operator_read_yaml_value ssh_key "${config_path}" 2>/dev/null || true)"
    fi
    local cfg_user
    cfg_user="$(operator_read_yaml_value ssh_user "${config_path}" 2>/dev/null || true)"
    if [[ -n "${cfg_user}" && "${_user}" == "${OPERATOR_DEFAULT_SSH_USER}" ]]; then
      _user="${cfg_user}"
    fi
    local cfg_root
    cfg_root="$(operator_read_yaml_value remote_root "${config_path}" 2>/dev/null || true)"
    if [[ -n "${cfg_root}" && "${_remote}" == "${OPERATOR_DEFAULT_REMOTE_ROOT}" ]]; then
      _remote="${cfg_root}"
    fi
  fi

  if [[ -z "${_host}" ]]; then
    case "${role}" in
      stage)
        _host="$(operator_read_yaml_value stage_host "${config_path}" 2>/dev/null || true)"
        ;;
      dev)
        _host="$(operator_read_yaml_value dev_host "${config_path}" 2>/dev/null || true)"
        ;;
    esac
  fi
}

operator_ssh_args() {
  local key="$1"
  local use_tty="${2:-0}"
  local -a args=(ssh -o BatchMode=yes -o ConnectTimeout=15)
  if [[ -n "${key}" ]]; then
    local expanded
    expanded="$(operator_expand_path "${key}")"
    if [[ ! -f "${expanded}" ]]; then
      echo "❌ SSH key not found: ${expanded}" >&2
      return 1
    fi
    args+=(-i "${expanded}")
  fi
  if [[ "${use_tty}" -eq 1 ]]; then
    args+=(-t)
  fi
  printf '%s\0' "${args[@]}"
}

operator_run_remote() {
  local user="$1"
  local host="$2"
  local key="$3"
  local remote_script="$4"
  local use_tty="${5:-0}"
  local dry_run="${6:-0}"

  if [[ "${dry_run}" -eq 1 ]]; then
    echo "=== DRY-RUN remote (${user}@${host}) ==="
    printf '%s\n' "${remote_script}"
    return 0
  fi

  local -a ssh_args=(ssh -o BatchMode=yes -o ConnectTimeout=15)
  if [[ -n "${key}" ]]; then
    local expanded
    expanded="$(operator_expand_path "${key}")"
    if [[ ! -f "${expanded}" ]]; then
      echo "❌ SSH key not found: ${expanded}" >&2
      return 1
    fi
    ssh_args+=(-i "${expanded}")
  fi
  if [[ "${use_tty}" -eq 1 ]]; then
    ssh_args+=(-t)
  fi
  ssh_args+=("${user}@${host}" bash -s)
  printf '%s\n' "${remote_script}" | "${ssh_args[@]}"
}
