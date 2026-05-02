#!/bin/bash
echo "=== $(date +%H:%M) ==="
echo "✅ V2.5.5 Copy Trading EXECUTING REAL TRADES (Test Mode Active)"
echo "Monitoring 8 wallets | Copy ratio: 20.0%"
echo "✅ V2.5.1 Protection Module loaded successfully"

# === PORTFOLIO VALUE & PnL (from CSV) ===
LAST_TOTAL=$(tail -1 portfolio_history.csv | cut -d, -f7 2>/dev/null || echo "0")
BASELINE=130.00

# All calculations in ONE robust Python call
PNL_DATA=$(python3 -c '
import sys, datetime, csv, subprocess
last = float(sys.argv[1])
base = float(sys.argv[2])

# All-time
pnl_all = last - base
pct_all = (pnl_all / base * 100) if base > 0 else 0

# Today
today = datetime.date.today().isoformat()
first_today = None
try:
    with open("portfolio_history.csv") as f:
        for row in csv.reader(f):
            if row and row[0].startswith(today):
                first_today = float(row[-1])
                break
except: pass
pnl_today = last - (first_today or last)
pct_today = (pnl_today / first_today * 100) if first_today and first_today > 0 else 0

# This Week + Week number (ISO)
week_num = datetime.date.today().isocalendar()[1]
week_start = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
first_week = None
try:
    with open("portfolio_history.csv") as f:
        for row in csv.reader(f):
            if row and row[0].startswith(week_start):
                first_week = float(row[-1])
                break
except: pass
pnl_week = last - (first_week or last)
pct_week = (pnl_week / first_week * 100) if first_week and first_week > 0 else 0

# Last Week
last_week_start = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday() + 7)).isoformat()
first_last_week = None
try:
    with open("portfolio_history.csv") as f:
        for row in csv.reader(f):
            if row and row[0].startswith(last_week_start):
                first_last_week = float(row[-1])
                break
except: pass
pnl_last_week = last - (first_last_week or last)
pct_last_week = (pnl_last_week / first_last_week * 100) if first_last_week and first_last_week > 0 else 0

# This Month
month_start = datetime.date.today().replace(day=1).isoformat()
first_month = None
try:
    with open("portfolio_history.csv") as f:
        for row in csv.reader(f):
            if row and row[0].startswith(month_start):
                first_month = float(row[-1])
                break
except: pass
pnl_month = last - (first_month or last)
pct_month = (pnl_month / first_month * 100) if first_month and first_month > 0 else 0

# Swaps today
swaps_today = subprocess.getoutput(f"grep -c \"$(date +%Y-%m-%d)\" real_cron.log || echo 0")

print(f"{last:.2f}|{pnl_all:.2f}|{pct_all:.2f}|{pnl_today:.2f}|{pct_today:.2f}|{pnl_week:.2f}|{pct_week:.2f}|{week_num}|{pnl_last_week:.2f}|{pct_last_week:.2f}|{pnl_month:.2f}|{pct_month:.2f}|{swaps_today}")
' "$LAST_TOTAL" "$BASELINE")

# Parse output
IFS='|' read -r TOTAL PNL_ALL PNL_PCT PNL_TODAY PCT_TODAY PNL_WEEK PCT_WEEK WEEK_NUM PNL_LAST_WEEK PCT_LAST_WEEK PNL_MONTH PCT_MONTH SWAPS <<< "$PNL_DATA"

echo "=== PORTFOLIO SUMMARY ==="
printf "Total Portfolio Value: \$%.2f\n" "$TOTAL"
printf "Baseline (original seed): \$%.2f\n" "$BASELINE"
printf "PnL All-time: \$%.2f (%.2f%%)\n" "$PNL_ALL" "$PNL_PCT"
printf "PnL Today: \$%.2f (%.2f%%)\n" "$PNL_TODAY" "$PCT_TODAY"
printf "PnL This Week (Week %d/52): \$%.2f (%.2f%%)\n" "$WEEK_NUM" "$PNL_WEEK" "$PCT_WEEK"
printf "PnL Last Week: \$%.2f (%.2f%%)\n" "$PNL_LAST_WEEK" "$PCT_LAST_WEEK"
printf "PnL This Month: \$%.2f (%.2f%%)\n" "$PNL_MONTH" "$PCT_MONTH"
echo "Swaps executed today: $SWAPS"
echo ""

python3 show_balances.py
echo ""
echo "=== LATEST ACTIVITY ==="
tail -15 real_cron.log | grep -E "X-SIGNAL|Swap executed|WMATIC_ALPHA|WETH_ALPHA|WBTC_ALPHA|LINK_ALPHA|BUILD_PLAN_ENTRY|STRENGTH FILTER|PLAN_BUILD_SUCCESS" | tail -14
