#!/usr/bin/env bash
# Unattended operator monitoring: periodic nanohealth + nanopnl + real_cron.log greps.
# Env: NANO_WATCH_INTERVAL_SECONDS (default 1800), NANO_WATCH_DURATION_SECONDS (default 43200),
#      NANO_WATCH_LOG (default ~/nanoclaw_watch.log), NANOCLAW_ROOT.
set -euo pipefail

ROOT="${NANOCLAW_ROOT:-$HOME/.nanobot/workspace/nanoclaw}"
LOG_FILE="${NANO_WATCH_LOG:-${HOME}/nanoclaw_watch.log}"
INTERVAL="${NANO_WATCH_INTERVAL_SECONDS:-1800}"
DURATION="${NANO_WATCH_DURATION_SECONDS:-43200}"

cd "${ROOT}" || {
  echo "nano_watch: cannot cd to ${ROOT}" >&2
  exit 1
}

PYTHON="python"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

_nano_watch_append_snapshot() {
  local cron_log="${ROOT}/real_cron.log"
  local health_line pnl_lines risk_line exec_line runway_line

  {
    echo "=== $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

    health_line="$("${PYTHON}" scripts/nanohealth.py 2>&1 | head -n 1 || true)"
    if [[ -z "${health_line//[[:space:]]/}" ]]; then
      health_line="nanohealth: (no output)"
    fi
    echo "${health_line}"

    pnl_lines="$(
      PYTHONIOENCODING=utf-8 "${PYTHON}" scripts/pnl_report.py 2>/dev/null \
        | grep -E 'TOTAL:|Stables|Session PnL|velocity_fills_session|turnover_multiple_session' \
        || true
    )"
    if [[ -n "${pnl_lines//[[:space:]]/}" ]]; then
      printf '%s\n' "${pnl_lines}"
    else
      echo "nanopnl: (no matching lines)"
    fi

    if [[ -f "${cron_log}" ]]; then
      risk_line="$(grep -E 'Risk=' "${cron_log}" 2>/dev/null | tail -n 1 || true)"
      exec_line="$(grep -E 'EXEC SUCCESS|EXEC FAILED' "${cron_log}" 2>/dev/null | tail -n 1 || true)"
      runway_line="$(grep -E 'FE STABLE RUNWAY' "${cron_log}" 2>/dev/null | tail -n 1 || true)"
    else
      risk_line=""
      exec_line=""
      runway_line=""
    fi

    if [[ -n "${risk_line}" ]]; then
      echo "risk: ${risk_line}"
    else
      echo "risk: (none)"
    fi
    if [[ -n "${exec_line}" ]]; then
      echo "exec: ${exec_line}"
    else
      echo "exec: (none)"
    fi
    if [[ -n "${runway_line}" ]]; then
      echo "runway: ${runway_line}"
    else
      echo "runway: (none)"
    fi
    echo "---"
  } >>"${LOG_FILE}"
}

_nano_watch_sleep_until() {
  local deadline="$1"
  local now remaining sleep_for
  now="$(date +%s)"
  remaining=$((deadline - now))
  if ((remaining <= 0)); then
    return 0
  fi
  sleep_for="${INTERVAL}"
  if ((remaining < sleep_for)); then
    sleep_for="${remaining}"
  fi
  sleep "${sleep_for}"
}

main() {
  local start deadline
  start="$(date +%s)"
  deadline=$((start + DURATION))

  mkdir -p "$(dirname "${LOG_FILE}")"
  {
    echo "nano_watch: start repo=${ROOT} interval=${INTERVAL}s duration=${DURATION}s log=${LOG_FILE}"
  } >>"${LOG_FILE}"

  while (( $(date +%s) < deadline )); do
    _nano_watch_append_snapshot
    _nano_watch_sleep_until "${deadline}"
  done

  echo "nano_watch: done (${LOG_FILE})"
}

main "$@"
