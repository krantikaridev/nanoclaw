#!/bin/bash
echo "=== $(date +%H:%M) ==="

echo "=== PORTFOLIO SUMMARY ==="
LAST_TOTAL=$(tail -1 portfolio_history.csv | cut -d, -f7)
BASELINE=130.00
PNL=$(python3 -c "last=float(\"$LAST_TOTAL\"); base=float(\"$BASELINE\"); print(f\"{last - base:.2f}\")")
PNL_PCT=$(python3 -c "last=float(\"$LAST_TOTAL\"); base=float(\"$BASELINE\"); print(f\"{(last - base) / base * 100:.2f}\")")

printf 'Total Portfolio Value: \$%.2f\n' "$LAST_TOTAL"
printf 'Baseline (original seed): \$%.2f\n' "$BASELINE"
printf 'PnL Today: \$%s (%.2f%%)\n' "$PNL" "$PNL_PCT"

python3 -c "
from clean_swap import get_balances
b = get_balances()
print(f\"USDT:{b.usdt:.2f}  USDC:{b.usdc:.2f}  WMATIC:{b.wmatic:.2f}  POL:{b.pol:.4f}\")
"

tail -15 real_cron.log | grep -E "X-SIGNAL|Swap executed|USDC:|WMATIC_ALPHA|FORCE|DEBUG|TP hit|EXIT SIGNAL|profit" | tail -8
