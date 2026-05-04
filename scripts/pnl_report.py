#!/usr/bin/env python3
import re

LOG_FILE = "real_cron.log"

def get_current_balance():
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()

    # === HIGHEST PRIORITY: Manual correct balance (your MetaMask values) ===
    for line in reversed(lines):
        if "MANUAL CORRECT BALANCE" in line or "Source=MetaMask" in line:
            m = re.search(r"USDC=\$?([\d.]+).*WMATIC=\$?([\d.]+).*USDT=\$?([\d.]+)", line)
            if m:
                usdc = float(m.group(1))
                wmatic = float(m.group(2))
                usdt = float(m.group(3))
                total = usdc + wmatic + usdt
                if total > 5:
                    return {"usdt": usdt, "usdc": usdc, "wmatic": wmatic, "total": total, "source": "MANUAL (MetaMask)"}

    # === SECOND PRIORITY: WALLET BALANCE lines (most reliable) ===
    for line in reversed(lines):
        m = re.search(r"WALLET BALANCE.*USDC=\$?([\d.]+)", line)
        if m:
            usdc = float(m.group(1))
            usdt = 0.0
            wmatic = 0.0
            idx = lines.index(line) if line in lines else -1
            if idx >= 0:
                for j in range(idx, min(idx + 5, len(lines))):
                    m_usdt = re.search(r"USDT=\$?([\d.]+)", lines[j])
                    if m_usdt: usdt = float(m_usdt.group(1))
                    m_w = re.search(r"WMATIC=\$?([\d.]+)", lines[j])
                    if m_w: wmatic = float(m_w.group(1))
            total = usdc + usdt + wmatic
            if total > 5 and wmatic < 15:   # only accept reasonable WMATIC
                return {"usdt": usdt, "usdc": usdc, "wmatic": wmatic, "total": total, "source": "WALLET BALANCE"}

    # === LAST RESORT: Real USDT line but ONLY if WMATIC looks sane (< $15) ===
    for line in reversed(lines):
        m = re.search(
            r"Real USDT:\s*\$?([\d.]+)\s*\|\s*USDC:\s*\$?([\d.]+)\s*\|\s*WMATIC:\s*\$?([\d.]+)",
            line, re.IGNORECASE
        )
        if m:
            usdt = float(m.group(1))
            usdc = float(m.group(2))
            wmatic = float(m.group(3))
            total = usdt + usdc + wmatic
            if total > 5 and wmatic < 15:   # reject stale $40+ WMATIC
                return {"usdt": usdt, "usdc": usdc, "wmatic": wmatic, "total": total, "source": "Real USDT line"}

    return None

def get_recent_trades(n=8):
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    trades = []
    for line in reversed(lines):
        if any(kw in line for kw in ["REAL TX HASH", "Swap executed", "PROTECTION TRIGGERED", "Swap confirmed"]):
            trades.append(line.strip()[:130])
            if len(trades) >= n:
                break
    return list(reversed(trades))

# === REPORT ===
bal = get_current_balance()

print("═══════════════════════════════════════════════")
print("           NANOC LAW PnL REPORT (FIXED v3)")
print("═══════════════════════════════════════════════")

if bal:
    print(f"💰 CURRENT BALANCE  (source: {bal['source']})")
    print(f"   USDC:   ${bal['usdc']:.2f}")
    print(f"   WMATIC: ${bal['wmatic']:.2f}")
    print(f"   USDT:   ${bal['usdt']:.2f}")
    print(f"   TOTAL:  ${bal['total']:.2f}")
    print()
else:
    print("No valid balance found.")

print("📈 RECENT TRADES (last 8)")
print("═══════════════════════════════════════════════")
for t in get_recent_trades():
    print(t)
print("═══════════════════════════════════════════════")
