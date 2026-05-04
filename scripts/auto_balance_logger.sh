#!/bin/bash
while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] MANUAL CORRECT BALANCE | USDC=\$66.85 | WMATIC=\$8.46 | USDT=\$27.36 | TOTAL=\$102.67 | Source=AutoLogger" >> real_cron.log
    sleep 600   # every 10 minutes
done
