#!/bin/bash
echo "=== NANOC LAW VM FIX $(date) ==="
pkill -9 node || true

# Zombies cannot be killed directly; only their parent can reap them.
ZOMBIES="$(ps -eo pid=,ppid=,stat=,comm= | awk '$3 ~ /^Z/ {print $1" "$2" "$4}')"
if [ -n "$ZOMBIES" ]; then
  echo "Found zombie processes (pid ppid comm):"
  echo "$ZOMBIES"
  echo "Attempting to terminate zombie parents so they can reap children..."
  echo "$ZOMBIES" | awk '{print $2}' | sort -u | while read -r PPID; do
    [ -n "$PPID" ] && kill -TERM "$PPID" 2>/dev/null || true
  done
  sleep 2
  # If still present, force kill parents (best-effort).
  ZOMBIES_AFTER="$(ps -eo pid=,ppid=,stat=,comm= | awk '$3 ~ /^Z/ {print $1" "$2" "$4}')"
  if [ -n "$ZOMBIES_AFTER" ]; then
    echo "Zombies still present after SIGTERM; forcing parent kill..."
    echo "$ZOMBIES_AFTER" | awk '{print $2}' | sort -u | while read -r PPID; do
      [ -n "$PPID" ] && kill -KILL "$PPID" 2>/dev/null || true
    done
  fi
else
  echo "No zombie processes detected."
fi

sync && sudo sysctl -w vm.drop_caches=3 2>/dev/null || true

ENV_PATH="${NANOCLAW_ENV_PATH:-$HOME/.nanobot/workspace/nanoclaw/.env}"

upsert_env() {
  local key="$1"
  local value="$2"
  local file="$3"
  if [ ! -f "$file" ]; then
    echo "⚠️ Env file not found: $file"
    return 1
  fi
  if grep -q "^${key}=" "$file"; then
    sed -i "s/^${key}=.*/${key}=${value}/" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
  return 0
}

if [ -n "${NANOCLAW_FIX_MAX_GWEI:-}" ]; then
  upsert_env "MAX_GWEI" "${NANOCLAW_FIX_MAX_GWEI}" "${ENV_PATH}" || true
fi
if [ -n "${NANOCLAW_FIX_URGENT_GWEI:-}" ]; then
  upsert_env "URGENT_GWEI" "${NANOCLAW_FIX_URGENT_GWEI}" "${ENV_PATH}" || true
fi
pkill -f clean_swap.py || true
sleep 3
echo "✅ VM fixed. Bot will restart via cron."
