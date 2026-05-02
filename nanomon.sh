#!/bin/bash
echo "=== $(date +%H:%M) ==="
python3 show_balances.py
tail -10 real_cron.log | grep -E "X-SIGNAL|Swap executed|WMATIC_ALPHA" | tail -6
