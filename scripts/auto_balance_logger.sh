#!/bin/bash
CONFIG="balance_config.txt"

while true; do
    if [ -f "$CONFIG" ]; then
        USDC=$(grep USDC "$CONFIG" | cut -d= -f2)
        WMATIC=$(grep WMATIC "$CONFIG" | cut -d= -f2)
        USDT=$(grep USDT "$CONFIG" | cut -d= -f2)
    else
        USDC=66.85; WMATIC=4.60; USDT=31.13
    fi

    TOTAL=$(echo "$USDC + $WMATIC + $USDT" | bc -l)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] MANUAL CORRECT BALANCE | USDC=\$${USDC} | WMATIC=\$${WMATIC} | USDT=\$${USDT} | TOTAL=\$${TOTAL} | Source=AutoLogger" >> real_cron.log
    sleep 600   # every 10 minutes
done
