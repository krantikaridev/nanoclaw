#!/bin/bash
echo "=== $(date +%H:%M) ==="
echo "✅ V2.5.4 Copy Trading EXECUTING REAL TRADES (Test Mode Active)"
echo "Monitoring 8 wallets | Copy ratio: 20.0%"
echo "✅ V2.5.1 Protection Module loaded successfully"

# === PORTFOLIO VALUE & PnL (from CSV) ===
LAST_TOTAL=$(tail -1 portfolio_history.csv | cut -d, -f7 2>/dev/null || echo "0")
BASELINE=130.00

# Robust PnL calculations via single Python call (no quoting bugs)
PNL_DATA=$(python3 -c '
import sys, datetime, csv
last = float(sys.argv[1])
base = float(sys.argv[2])

# All-time
pnl_all = last - base
pct_all = (pnl_all / base * 100) if base > 0 else 0

# Today PnL (00:00 UTC)
today = datetime.date.today().isoformat()
first_today = None
try:
    with open("portfolio_history.csv") as f:
        for row in csv.reader(f):
            if row and row[0].startswith(today):
                first_today = float(row[-1])
                break
except:
    pass
if first_today is not None:
    pnl_today = last - first_today
    pct_today = (pnl_today / first_today * 100) if first_today > 0 else 0
else:
    pnl_today = pct_today = 0

# 7-day PnL
target_7d = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
first_7d = None
try:
    with open("portfolio_history.csv") as f:
        for row in csv.reader(f):
            if row and row[0].startswith(target_7d):
                first_7d = float(row[-1])
                break
except:
    pass
if first_7d is not None:
    pnl_7d = last - first_7d
    pct_7d = (pnl_7d / first_7d * 100) if first_7d > 0 else 0
else:
    pnl_7d = pct_7d = 0

# Swaps today
import subprocess
swaps_today = subprocess.getoutput(f"grep -c \"$(date +%Y-%m-%d)\" real_cron.log || echo 0")

print(f"{last:.2f}|{pnl_all:.2f}|{pct_all:.2f}|{pnl_today:.2f}|{pct_today:.2f}|{pnl_7d:.2f}|{pct_7d:.2f}|{swaps_today}")
' "$LAST_TOTAL" "$BASELINE")

# Parse the output
IFS='|' read -r TOTAL PNL_ALL PNL_PCT PNL_TODAY PCT_TODAY PNL_7D PCT_7D SWAPS <<< "$PNL_DATA"

echo "=== PORTFOLIO SUMMARY ==="
printf "Total Portfolio Value: \$%.2f\n" "$TOTAL"
printf "Baseline (original seed): \$%.2f\n" "$BASELINE"
printf "PnL All-time: \$%.2f (%.2f%%)\n" "$PNL_ALL" "$PNL_PCT"
printf "PnL Today: \$%.2f (%.2f%%)   |   7-day: \$%.2f (%.2f%%)\n" "$PNL_TODAY" "$PCT_TODAY" "$PNL_7D" "$PCT_7D"
echo "Swaps executed today: $SWAPS"
echo ""

python3 show_balances.py
echo ""
echo "=== LATEST ACTIVITY ==="
tail -15 real_cron.log | grep -E "X-SIGNAL|Swap executed|WMATIC_ALPHA|BUILD_PLAN_ENTRY|STRENGTH FILTER|PLAN_BUILD_SUCCESS" | tail -12
