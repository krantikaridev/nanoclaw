#!/usr/bin/env bash
# Pre-bootstrap checks — laptop + optional remote VM probe.
#
# Usage:
#   ./scripts/dev_preflight.sh --role dev
#   ./scripts/dev_preflight.sh --host NEW_IP --key ~/.ssh/key.pem --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/operator_ssh.sh
source "${SCRIPT_DIR}/lib/operator_ssh.sh"

CONFIG_PATH="${OPERATOR_DEFAULT_CONFIG}"
SSH_USER="${OPERATOR_DEFAULT_SSH_USER}"
SSH_KEY=""
SSH_HOST=""
ROLE="dev"
REMOTE_ROOT="${OPERATOR_DEFAULT_REMOTE_ROOT}"
DRY_RUN=0
SKIP_REMOTE=0

_dev_preflight_usage() {
  cat <<'EOF'
Usage: dev_preflight.sh [options]

Checks before dev_bootstrap.sh:
  - Local: ssh client, config/host resolved, optional SSH key file
  - Local: Polygon RPC reachability (public endpoint)
  - Remote (unless --skip-remote): ssh, python3, git, disk space

Options:
  --config PATH     Operator config (default: ~/.nanoclaw/config.yaml)
  --role ROLE       stage | dev (default: dev)
  --host HOST       VM IP (overrides config)
  --user USER       SSH user (default: ubuntu)
  --key PATH        SSH private key
  --remote PATH     Remote repo root
  --dry-run         Print checks without executing remote SSH
  --skip-remote     Local checks only
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG_PATH="$2"; shift 2 ;;
    --role) ROLE="$2"; shift 2 ;;
    --host) SSH_HOST="$2"; shift 2 ;;
    --user) SSH_USER="$2"; shift 2 ;;
    --key) SSH_KEY="$2"; shift 2 ;;
    --remote) REMOTE_ROOT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --skip-remote) SKIP_REMOTE=1; shift ;;
    -h | --help) _dev_preflight_usage; exit 0 ;;
    *) echo "❌ unknown arg: $1" >&2; _dev_preflight_usage; exit 1 ;;
  esac
done

operator_load_ssh_config "${CONFIG_PATH}" SSH_HOST SSH_KEY SSH_USER REMOTE_ROOT "${ROLE}"

FAIL=0
_pass() { echo "OK  $*"; }
_fail() { echo "FAIL $*"; FAIL=1; }
_info() { echo "INFO $*"; }

echo "=== dev_preflight | $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC ==="
echo "role=${ROLE} host=${SSH_HOST:-<unset>} remote=${REMOTE_ROOT} dry_run=${DRY_RUN}"

if ! command -v ssh >/dev/null 2>&1; then
  _fail "ssh client not in PATH"
else
  _pass "ssh client present"
fi

if [[ -z "${SSH_HOST}" ]]; then
  _fail "no host — set dev_host in ${CONFIG_PATH} or pass --host"
fi

if [[ -n "${SSH_KEY}" ]]; then
  expanded="$(operator_expand_path "${SSH_KEY}")"
  if [[ -f "${expanded}" ]]; then
    _pass "SSH key file exists: ${expanded}"
  else
    _fail "SSH key missing: ${expanded}"
  fi
else
  _info "no --key / ssh_key in config — using ssh-agent or default keys"
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  _info "dry-run: would probe RPC https://polygon.publicnode.com"
else
  rpc_out="$(curl -sS --max-time 10 -X POST -H "Content-Type: application/json" \
    --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
    https://polygon.publicnode.com 2>&1)" || rpc_out=""
  if echo "${rpc_out}" | grep -q '"result"'; then
    _pass "Polygon RPC probe (local curl)"
  else
    _fail "Polygon RPC probe failed"
  fi
fi

if [[ "${SKIP_REMOTE}" -eq 1 ]]; then
  _info "skip-remote done"
  if [[ "${FAIL}" -ne 0 ]]; then
    echo "=== dev_preflight: FAIL ==="
    exit 1
  fi
  echo "=== dev_preflight: PASS ==="
  exit 0
fi

REMOTE_CHECK=$(cat <<EOF
set -euo pipefail
echo "remote_host=\$(hostname -f 2>/dev/null || hostname)"
command -v python3 >/dev/null && python3 --version | head -1
command -v git >/dev/null && git --version | head -1
df -h / | tail -1
test -d '${REMOTE_ROOT}' && echo "remote_root_exists=yes" || echo "remote_root_exists=no"
EOF
)

if [[ "${DRY_RUN}" -eq 1 ]]; then
  _info "dry-run: would SSH ${SSH_USER}@${SSH_HOST} for python3/git/df"
  operator_run_remote "${SSH_USER}" "${SSH_HOST}" "${SSH_KEY}" "${REMOTE_CHECK}" 0 1
else
  if operator_run_remote "${SSH_USER}" "${SSH_HOST}" "${SSH_KEY}" "${REMOTE_CHECK}" 0 0; then
    _pass "remote SSH probe"
  else
    _fail "remote SSH probe (${SSH_USER}@${SSH_HOST})"
  fi
fi

if [[ "${FAIL}" -ne 0 ]]; then
  echo "=== dev_preflight: FAIL ==="
  exit 1
fi
echo "=== dev_preflight: PASS ==="
