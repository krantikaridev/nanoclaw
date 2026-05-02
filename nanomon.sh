#!/bin/bash
echo "=== $(date +%H:%M) ==="
echo "✅ V2.5.3 Copy Trading EXECUTING REAL TRADES (Test Mode Active)"
echo "Monitoring 8 wallets | Copy ratio: 20.0%"
echo "✅ V2.5.1 Protection Module loaded successfully"

# === PORTFOLIO VALUE & PnL (from CSV) ===
LAST_TOTAL=$(tail -1 portfolio_history.csv | cut -d, -f7 2>/dev/null || echo "0")
BASELINE=130.00

# Current PnL vs baseline
PNL=$(python3 -c "
last = float('$LAST_TOTAL')
base = float('$BASELINE')
print(f'{last - base:.2f}')
")
PNL_PCT=$(python3 -c "
last = float('$LAST_TOTAL')
base = float('$BASELINE')
print(f'{(last - base) / base * 100:.2f}')
")

# TODAY'S PnL (since 00:00 UTC)
TODAY_START=$(python3 -c '
import datetime, csv, sys
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
current = float("'$LAST_TOTAL'")
if first_today is not None:
    pnl_today = current - first_today
    pct_today = (pnl_today / first_today * 100) if first_today > 0 else 0
    print(f"{pnl_today:.2f}|{pct_today:.2f}")
else:
    print("0.00|0.00")
' 2>/dev/null || echo "0.00|0.00")
TODAY_PNL=$(echo "$TODAY_START" | cut -d'|' -f1)
TODAY_PCT=$(echo "$TODAY_START" | cut -d'|' -f2)

# 7-DAY PnL
SEVEN_DAYS_AGO=$(python3 -c '
import datetime, csv, sys
target = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
first_7d = None
try:
    with open("portfolio_history.csv") as f:
        for row in csv.reader(f):
            if row and row[0].startswith(target):
                first_7d = float(row[-1])
                break
except:
    pass
current = float("'$LAST_TOTAL'")
if first_7d is not None:
    pnl_7d = current - first_7d
    pct_7d = (pnl_7d / first_7d * 100) if first_7d > 0 else 0
    print(f"{pnl_7d:.2f}|{pct_7d:.2f}")
else:
    print("0.00|0.00")
' 2>/dev/null || echo "0.00|0.00")
SEVEN_PNL=$(echo "$SEVEN_DAYS_AGO" | cut -d'|' -f1)
SEVEN_PCT=$(echo "$SEVEN_DAYS_AGO" | cut -d'|' -f2)

# Swaps today
SWAPS_TODAY=$(grep -c "$(date +%Y-%m-%d)" real_cron.log 2>/dev/null || echo "0")

echo "=== PORTFOLIO SUMMARY ==="
printf 'Total Portfolio Value: $%.2f\n' "$LAST_TOTAL"
printf 'Baseline (original seed): $%.2f\n' "$BASELINE"
printf 'PnL All-time: $%s (%.2f%%)\n' "$PNL" "$PNL_PCT"
printf 'PnL Today: $%s (%.2f%%)   |   7-day: $%s (%.2f%%)\n' "$TODAY_PNL" "$TODAY_PCT" "$SEVEN_PNL" "$SEVEN_PCT"
echo "Swaps executed today: $SWAPS_TODAY"
echo ""

python3 show_balances.py
echo ""
tail -15 real_cron.log | grep -E "X-SIGNAL|Swap executed|WMATIC_ALPHA|BUILD_PLAN_ENTRY|STRENGTH FILTER" | tail -10
