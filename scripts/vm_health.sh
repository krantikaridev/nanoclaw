#!/bin/bash
echo "=== NANOC LAW VM HEALTH CHECK $(date) ==="

echo -e "\n[1] CPU & Load"
uptime && top -bn1 | head -15

echo -e "\n[2] Memory"
free -h && cat /proc/meminfo | head -5

echo -e "\n[3] Storage"
df -h && du -sh /home/workdir/* 2>/dev/null | head -10

echo -e "\n[4] Disk I/O"
iostat -x 1 3 2>/dev/null || echo "iostat not installed (install sysstat if needed)"

echo -e "\n[5] Python Bot Processes"
ps aux | grep -E "python|clean_swap|nanoclaw" | grep -v grep

echo -e "\n[6] Cron Status"
crontab -l 2>/dev/null | grep -E "nanoclaw|clean_swap" || echo "No nanoclaw cron found"

echo -e "\n[7] Recent Logs (last 50 lines)"
tail -50 /home/workdir/artifacts/real_cron.log 2>/dev/null || tail -50 real_cron.log 2>/dev/null || echo "Log file not found"

echo -e "\n[8] Gas & RPC Check"
RPC_URL="${NANOCLAW_RPC_URL:-https://polygon.publicnode.com}"
RPC_PAYLOAD='{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
RPC_OUT="$(curl -sS --fail --max-time 10 -X POST -H "Content-Type: application/json" --data "$RPC_PAYLOAD" "$RPC_URL" 2>&1)"
RPC_RC=$?
if [ $RPC_RC -ne 0 ]; then
  echo "RPC check FAILED (curl exit $RPC_RC) for $RPC_URL"
  echo "$RPC_OUT" | head -c 400
else
  if echo "$RPC_OUT" | grep -q '"result"'; then
    echo "RPC check OK for $RPC_URL"
    echo "$RPC_OUT" | head -c 200
  else
    echo "RPC check INCONCLUSIVE for $RPC_URL (missing \"result\")"
    echo "$RPC_OUT" | head -c 400
  fi
fi

echo -e "\n=== HEALTH CHECK COMPLETE ==="
