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
echo "--- process (cron one-shot: empty pgrep between cycles is NORMAL) ---"
if pgrep -af clean_swap.py; then
  echo "INFO clean_swap mid-cycle"
else
  echo "INFO no clean_swap in pgrep (expected between */2 cron ticks)"
fi
if crontab -l 2>/dev/null | grep -E 'clean_swap|nanoclaw' | head -3; then
  echo "OK cron watchdog present"
else
  echo "WARN no clean_swap cron — cycles only run after manual nanoup"
fi
pgrep -af nano_watch.sh 2>/dev/null || echo "INFO nano_watch not running (optional)"

echo ""
echo "--- log freshness (last ~15 min) ---"
python3 - <<'PY'
import re
import time
from pathlib import Path
p = Path("real_cron.log")
if not p.is_file():
    print("FAIL no real_cron.log")
    raise SystemExit(0)
text = p.read_text(encoding="utf-8", errors="replace")[-120000:]
# ISO-ish timestamps in log lines
hits = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
if hits:
    from datetime import datetime, timezone
    last = hits[-1]
    try:
        ts = datetime.strptime(last, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        age = time.time() - ts.timestamp()
        print(f"last_log_ts={last}Z age_sec={age:.0f}")
        if age < 900:
            print("OK recent cycle activity")
        else:
            print("WARN log stale >15m — check cron or run nanoup")
    except ValueError:
        print(f"last_log_ts={last} (parse skipped)")
else:
    tail = text.strip().splitlines()[-1] if text.strip() else ""
    print(f"no timestamp in tail; last_line={tail[:120]!r}")
PY

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
echo "--- unpause_readiness (hard gates — Grok F / freeze lift) ---"
python3 scripts/unpause_readiness.py 2>/dev/null || echo "WARN unpause_readiness failed"

echo ""
echo "PASS = paused+lock + recent log activity + pause skip lines + cron present"
echo "NOTE: pgrep clean_swap often empty — bot is one cycle per cron tick, then exits"
echo "TIP: after git pull use nanodeploy (nanoup + all checks in one command)"
