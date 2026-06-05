#!/usr/bin/env bash
# Ephemeral dev VM bootstrap — SSH-only, cloud-agnostic.
#
# Usage:
#   ./scripts/dev_bootstrap.sh --role dev --branch V4-play --seed-usd 50 \
#     --secrets ~/.nanoclaw/secrets.dev.env
#   ./scripts/dev_bootstrap.sh --host NEW_IP --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/operator_ssh.sh
source "${SCRIPT_DIR}/lib/operator_ssh.sh"

CONFIG_PATH="${OPERATOR_DEFAULT_CONFIG}"
SSH_USER="${OPERATOR_DEFAULT_SSH_USER}"
SSH_KEY=""
SSH_HOST=""
ROLE="dev"
REMOTE_ROOT="${OPERATOR_DEFAULT_REMOTE_ROOT}"
BRANCH="V4-play"
SEED_USD="50"
SECRETS_FILE=""
REPO_URL="https://github.com/krantikaridev/nanoclaw.git"
CLOUD="generic"
DRY_RUN=0
SKIP_CRON=0

_dev_bootstrap_usage() {
  cat <<'EOF'
Usage: dev_bootstrap.sh [options]

Bootstrap ephemeral lab VM:
  - clone/pull branch into ~/.nanobot/workspace/nanoclaw
  - venv + pip install
  - .env from .env.dev.example + secrets merge + STAGE_SEED_USD
  - cron watchdog for clean_swap.py
  - ~/.local/bin nano shims

Options:
  --config PATH       Operator config (default: ~/.nanoclaw/config.yaml)
  --role ROLE         dev (default) | stage
  --host HOST         VM IP
  --user USER         SSH user (default: ubuntu)
  --key PATH          SSH private key
  --remote PATH       Remote repo root
  --branch NAME       Git branch (default: V4-play)
  --seed-usd N        STAGE_SEED_USD on VM (default: 50)
  --secrets PATH      secrets.dev.env on laptop (required unless --dry-run)
  --repo-url URL      Git remote (default: github nanoclaw)
  --cloud NAME        generic only (default: generic)
  --skip-cron         Do not install cron snippet
  --dry-run           Print remote script only
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
    --branch) BRANCH="$2"; shift 2 ;;
    --seed-usd) SEED_USD="$2"; shift 2 ;;
    --secrets) SECRETS_FILE="$2"; shift 2 ;;
    --repo-url) REPO_URL="$2"; shift 2 ;;
    --cloud) CLOUD="$2"; shift 2 ;;
    --skip-cron) SKIP_CRON=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h | --help) _dev_bootstrap_usage; exit 0 ;;
    *) echo "❌ unknown arg: $1" >&2; _dev_bootstrap_usage; exit 1 ;;
  esac
done

if [[ "${CLOUD}" != "generic" ]]; then
  echo "❌ only --cloud generic is supported (got ${CLOUD})" >&2
  exit 1
fi

operator_load_ssh_config "${CONFIG_PATH}" SSH_HOST SSH_KEY SSH_USER REMOTE_ROOT "${ROLE}"

if [[ -z "${SSH_HOST}" ]]; then
  echo "❌ no host — set dev_host in ${CONFIG_PATH} or pass --host" >&2
  exit 1
fi

if [[ "${DRY_RUN}" -eq 0 && -z "${SECRETS_FILE}" ]]; then
  echo "❌ --secrets required (e.g. ~/.nanoclaw/secrets.dev.env)" >&2
  exit 1
fi

if [[ -n "${SECRETS_FILE}" && "${DRY_RUN}" -eq 0 ]]; then
  expanded_secrets="$(operator_expand_path "${SECRETS_FILE}")"
  if [[ ! -f "${expanded_secrets}" ]]; then
    echo "❌ secrets file not found: ${expanded_secrets}" >&2
    exit 1
  fi
fi

SECRETS_B64=""
if [[ -n "${SECRETS_FILE}" && -f "$(operator_expand_path "${SECRETS_FILE}" 2>/dev/null || echo "")" ]]; then
  SECRETS_B64="$(base64 -w0 "$(operator_expand_path "${SECRETS_FILE}")" 2>/dev/null || base64 "$(operator_expand_path "${SECRETS_FILE}")" | tr -d '\n')"
fi

INSTALL_CRON=1
if [[ "${SKIP_CRON}" -eq 1 ]]; then
  INSTALL_CRON=0
fi

REMOTE_SCRIPT=$(cat <<EOF
set -euo pipefail
REMOTE_ROOT='${REMOTE_ROOT}'
BRANCH='${BRANCH}'
REPO_URL='${REPO_URL}'
SEED_USD='${SEED_USD}'
INSTALL_CRON=${INSTALL_CRON}
SECRETS_B64='${SECRETS_B64}'

echo "=== dev_bootstrap remote | \$(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
mkdir -p "\$(dirname "\${REMOTE_ROOT}")"

if [[ -d "\${REMOTE_ROOT}/.git" ]]; then
  echo "[1/7] git pull existing checkout"
  cd "\${REMOTE_ROOT}"
  git fetch --all --prune
  git checkout "\${BRANCH}"
  git pull --ff-only
else
  echo "[1/7] git clone"
  rm -rf "\${REMOTE_ROOT}"
  git clone --branch "\${BRANCH}" --depth 1 "\${REPO_URL}" "\${REMOTE_ROOT}"
  cd "\${REMOTE_ROOT}"
fi

echo "[2/7] python venv"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt

echo "[3/7] .env from .env.dev.example"
if [[ -f .env.dev.example ]]; then
  cp .env.dev.example .env
else
  echo "WARN .env.dev.example missing — touch empty .env"
  : > .env
fi

echo "[4/7] merge secrets overlay"
if [[ -n "\${SECRETS_B64}" ]]; then
  echo "\${SECRETS_B64}" | base64 -d > /tmp/nanoclaw_secrets.env
  while IFS= read -r line || [[ -n "\${line}" ]]; do
    [[ -z "\${line}" || "\${line}" =~ ^[[:space:]]*# ]] && continue
    key="\${line%%=*}"
    [[ -z "\${key}" ]] && continue
    if grep -q "^\${key}=" .env 2>/dev/null; then
      sed -i "s|^\${key}=.*|\${line}|" .env
    else
      printf '%s\n' "\${line}" >> .env
    fi
  done < /tmp/nanoclaw_secrets.env
  rm -f /tmp/nanoclaw_secrets.env
else
  echo "INFO no secrets payload (dry-run or missing file)"
fi

if grep -q '^STAGE_SEED_USD=' .env 2>/dev/null; then
  sed -i "s/^STAGE_SEED_USD=.*/STAGE_SEED_USD=\${SEED_USD}/" .env
else
  echo "STAGE_SEED_USD=\${SEED_USD}" >> .env
fi
if grep -q '^NANOCLAW_ROLE=' .env 2>/dev/null; then
  sed -i "s/^NANOCLAW_ROLE=.*/NANOCLAW_ROLE=dev/" .env
else
  echo "NANOCLAW_ROLE=dev" >> .env
fi

echo "[5/7] compile check"
python -m compileall -q .

echo "[6/7] nano shims"
bash scripts/nanobot_aliases.sh --install || echo "WARN shim install failed"

if [[ "\${INSTALL_CRON}" -eq 1 ]]; then
  echo "[7/7] cron watchdog"
  CRON_MARK="# nanoclaw-dev-bootstrap"
  CRON_LINE="*/2 * * * * pgrep -f clean_swap.py >/dev/null || (cd \${REMOTE_ROOT} && nohup ./.venv/bin/python clean_swap.py >> real_cron.log 2>&1 &)"
  (crontab -l 2>/dev/null | grep -v "clean_swap.py" | grep -v "\${CRON_MARK}" || true; echo "\${CRON_MARK}"; echo "\${CRON_LINE}") | crontab -
else
  echo "[7/7] skip cron (--skip-cron)"
fi

echo "✅ dev_bootstrap complete | branch=\$(git rev-parse --short HEAD) | \${REMOTE_ROOT}"
EOF
)

echo "=== dev_bootstrap | $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC ==="
echo "target=${SSH_USER}@${SSH_HOST} branch=${BRANCH} seed_usd=${SEED_USD} cloud=${CLOUD}"

operator_run_remote "${SSH_USER}" "${SSH_HOST}" "${SSH_KEY}" "${REMOTE_SCRIPT}" 0 "${DRY_RUN}"
