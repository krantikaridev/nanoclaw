#!/usr/bin/env bash
# Teardown ephemeral dev VM — stop cron, optional wipe. Wallet keeps on-chain funds.
#
# Usage:
#   ./scripts/dev_destroy.sh --role dev
#   ./scripts/dev_destroy.sh --host NEW_IP --wipe --dry-run
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
WIPE=0
DRY_RUN=0

_dev_destroy_usage() {
  cat <<'EOF'
Usage: dev_destroy.sh [options]

Stops nanoclaw cron and clean_swap on dev VM. Optional --wipe removes checkout.

Options:
  --config PATH     Operator config
  --role ROLE       dev (default)
  --host HOST       VM IP
  --user USER       SSH user
  --key PATH        SSH key
  --remote PATH     Remote repo root
  --wipe            Remove ~/.nanobot/workspace/nanoclaw (keeps wallet on-chain)
  --dry-run         Print remote script only
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
    --wipe) WIPE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h | --help) _dev_destroy_usage; exit 0 ;;
    *) echo "❌ unknown arg: $1" >&2; _dev_destroy_usage; exit 1 ;;
  esac
done

operator_load_ssh_config "${CONFIG_PATH}" SSH_HOST SSH_KEY SSH_USER REMOTE_ROOT "${ROLE}"

if [[ -z "${SSH_HOST}" ]]; then
  echo "❌ no host — set dev_host in ${CONFIG_PATH} or pass --host" >&2
  exit 1
fi

REMOTE_SCRIPT=$(cat <<EOF
set -euo pipefail
REMOTE_ROOT='${REMOTE_ROOT}'
WIPE=${WIPE}

echo "=== dev_destroy remote | \$(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

echo "[1/3] stop clean_swap"
pkill -f clean_swap.py 2>/dev/null || true
sleep 1
pgrep -af clean_swap.py 2>/dev/null || echo "INFO no clean_swap process"

echo "[2/3] remove cron lines"
(crontab -l 2>/dev/null | grep -v "clean_swap.py" | grep -v "nanoclaw-dev-bootstrap" || true) | crontab -
crontab -l 2>/dev/null | grep -E 'clean_swap|nanoclaw' || echo "OK cron cleared"

if [[ "\${WIPE}" -eq 1 ]]; then
  echo "[3/3] wipe \${REMOTE_ROOT}"
  rm -rf "\${REMOTE_ROOT}"
  echo "✅ wiped \${REMOTE_ROOT} (wallet unchanged on-chain)"
else
  echo "[3/3] keep checkout at \${REMOTE_ROOT} (cron stopped)"
  echo "✅ dev_destroy complete — repo kept, cron off"
fi
EOF
)

echo "=== dev_destroy | $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC ==="
echo "target=${SSH_USER}@${SSH_HOST} wipe=${WIPE}"

operator_run_remote "${SSH_USER}" "${SSH_HOST}" "${SSH_KEY}" "${REMOTE_SCRIPT}" 0 "${DRY_RUN}"
