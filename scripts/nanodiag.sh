#!/usr/bin/env bash
# Paranoid leave monitor — one screen for Terminus / iPhone.
# Usage: cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate && nanodiag
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

echo "=== nanodiag | $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC | $(TZ=Asia/Kolkata date +%H:%M) IST ==="
git log -1 --oneline 2>/dev/null || echo "git: n/a"

echo ""
echo "--- process ---"
if pgrep -af clean_swap.py; then
  echo "OK clean_swap running"
else
  echo "FAIL no clean_swap — run: NANOUP_AUTOSTASH=1 nanoup"
fi
pgrep -af nano_watch.sh 2>/dev/null || echo "INFO nano_watch not running (optional)"

echo ""
echo "--- control.json (leave gate) ---"
python3 - <<'PY'
import json
from pathlib import Path
p = Path("control.json")
c = json.loads(p.read_text()) if p.is_file() else {}
paused = bool(c.get("paused"))
lock = bool(c.get("operator_pause_lock"))
print(f"paused={paused} operator_pause_lock={lock} reason={c.get('reason', '')!r}")
if paused and lock:
    print("OK leave gate — new entries blocked")
elif paused:
    print("WARN paused but no operator_pause_lock — external layer may unpause")
else:
    print("FAIL NOT PAUSED — bot may trade entries")
PY

echo ""
echo "--- nh (RPC) ---"
python scripts/nanohealth.py 2>&1 | tail -1 || echo "WARN nanohealth failed"

echo ""
echo "--- nanopnl ---"
python scripts/pnl_report.py 2>/dev/null | grep -E 'TOTAL|Stables|Session PnL|velocity' || echo "WARN pnl_report failed"

echo ""
echo "--- last pause / skip (must see while on leave) ---"
grep -E '\[CONTROL\] paused=True|skipping X-signal entry|skipping new entry|skipping copy-trade' real_cron.log 2>/dev/null | tail -3 || echo "WARN no pause lines in log yet"

echo ""
echo "--- recent fills (should be OLD while paused) ---"
grep 'EXEC SUCCESS' real_cron.log 2>/dev/null | tail -1 || echo "none in log"

echo ""
echo "--- last cycle tail ---"
tail -4 real_cron.log 2>/dev/null || echo "no real_cron.log"

echo ""
echo "PASS = paused+lock + clean_swap + pause skip lines + no new EXEC SUCCESS in tail"
echo "Grok/iPhone: paste this block if something looks FAIL"
