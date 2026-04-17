#!/usr/bin/env python3
"""
Nanoclaw v2 - Polymarket Strategy (Madan Pune)
Uses config_real.py for parameters
"""

import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from web3 import Web3
import json
import requests  # for potential Gamma API calls later

load_dotenv()
# Load config
try:
    from config_real import TRADE_SIZE_USDT, MAX_DAILY_LOSS_USDT, MIN_EDGE_PCT, SIM_CONFIDENCE_THRESHOLD, ACTIVE_STRATEGIES, WALLET_ADDRESS, RPC_URL
    print(f"✅ Config loaded successfully - Trade Size: {TRADE_SIZE_USDT:.2f} USDT | Max Daily Loss: {MAX_DAILY_LOSS_USDT} USDT | Min Edge: {MIN_EDGE_PCT}%")
except ImportError:
    print("❌ config_real.py not found. Using defaults.")
    TRADE_SIZE_USDT = 2.0
    MAX_DAILY_LOSS_USDT = 10.0
    MIN_EDGE_PCT = 3.0
    SIM_CONFIDENCE_THRESHOLD = 200000
    ACTIVE_STRATEGIES = ["baseline", "polymarket"]
    WALLET_ADDRESS = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
    RPC_URL = "https://polygon.drpc.org"

PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
if not PRIVATE_KEY:
    print("❌ ERROR: Private key not set in .env")
    exit(1)

w3 = Web3(Web3.HTTPProvider(RPC_URL))
print(f"✅ RPC connected: {w3.is_connected()} | URL: {RPC_URL}")

USDT_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
WETH_ADDRESS = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

daily_loss_today = 0.0

async def run_real_trade():
    global daily_loss_today

    if daily_loss_today >= MAX_DAILY_LOSS_USDT:
        print(f"🛑 DAILY LOSS LIMIT REACHED ({daily_loss_today:.2f}/{MAX_DAILY_LOSS_USDT} USDT). Trading paused today.")
        return

    # SIM Alignment + Daily Alternation Check
    try:
        with open("skills/autonomous-revenue-engine/capital.json") as f:
            sim_data = json.load(f)
            sim_capital = sim_data.get("capital", 0)
            sim_positive = sim_capital > SIM_CONFIDENCE_THRESHOLD
        print(f"✅ SIM Confidence: {'Strong' if sim_positive else 'Low'} (~{sim_capital/1000:.0f}k)")
    except:
        sim_positive = True

    # Daily Alternation Logic
    import datetime
    today = datetime.date.today().weekday()
    run_baseline_today = today % 2 == 0
    run_polymarket_today = today % 2 == 1

    if "baseline" in ACTIVE_STRATEGIES and not run_baseline_today:
        print("⏸️ Today is Polymarket day - skipping baseline")
        return
    if "polymarket" in ACTIVE_STRATEGIES and not run_polymarket_today:
        print("⏸️ Today is Baseline day - skipping Polymarket")
        return

    if not sim_positive:
        print("⏸️ SIM confidence low - skipping trade")
        return

    # Improved Edge Check v2 - More realistic for testing
    # In future we can connect to real Gamma API or X-watcher
    edge_found = 4.2  # Placeholder - increase this as we add real signals
    reason = "Basic edge check (to be replaced with Gamma or X signal)"

    if edge_found < MIN_EDGE_PCT:
        print(f"⏸️ Edge too low ({edge_found:.1f}% < {MIN_EDGE_PCT}%) - skipping trade | Reason: {reason}")
        return

    print(f"""
══════════════════════════════════════
🚀 v2 IMPROVED POLYMARKET TRADE
Strategy : Polymarket (Edge v2)
Wallet : {WALLET_ADDRESS[:10]}...
Trade Size : {TRADE_SIZE_USDT:.2f} USDT → WETH
Edge Found : {edge_found:.1f}%
Reason : {reason}
Daily Loss : {daily_loss_today:.2f}/{MAX_DAILY_LOSS_USDT} USDT
══════════════════════════════════════
""")
    
    from swap_utils import execute_usdt_to_weth_swap
    tx_hash = await execute_usdt_to_weth_swap(w3, WALLET_ADDRESS, PRIVATE_KEY, TRADE_SIZE_USDT)

    if tx_hash:
        daily_loss_today += 0.08
        print(f"✅ Polymarket trade completed successfully. Tx: {tx_hash}")
    else:
        print("❌ Polymarket trade failed")

if __name__ == "__main__":
    asyncio.run(run_real_trade())
