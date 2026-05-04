#!/usr/bin/env python3
import re

LOG_FILE = "real_cron.log"

def get_latest_balance():
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()

    for line in reversed(lines):
        # Match: WALLET BALANCE | USDC=$93.87
        m = re.search(r"WALLET BALANCE.*USDC=\$?([\d.]+)", line)
        if m:
            usdc = float(m.group(1))
            # Try to get WMATIC from nearby lines
            wmatic = 0.0
            for j in range(len(lines) - 1, max(0, len(lines) - 10), -1):
                m2 = re.search(r"WMATIC=\$?([\d.]+)", lines[j])
                if m2:
                    wmatic = float(m2.group(1))
                    break
            total = usdc + wmatic
            return {"usdc": usdc, "wmatic": wmatic, "total": total}
    return None

bal = get_latest_balance()

print("═══════════════════════════════════════════════")
print("           NANOC LAW PnL REPORT")
print("═══════════════════════════════════════════════")

if bal:
    print(f"💰 CURRENT BALANCE")
    print(f"   USDC:   ${bal['usdc']:.2f}")
    print(f"   WMATIC: ${bal['wmatic']:.2f}")
    print(f"   TOTAL:  ${bal['total']:.2f}")
else:
    print("No balance data found yet.")

print()
print("📈 RECENT TRADES (last 10)")
print("═══════════════════════════════════════════════")
