#!/usr/bin/env python3
"""
Nanoclaw v2 - Real Money Runner (Madan Pune)
Uses config_real.py for all changeable parameters
"""

import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from web3 import Web3
import json

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
if not PRIVATE_KEY or "YOUR_PRIVATE_KEY_HERE" in PRIVATE_KEY:
    print("❌ ERROR: Private key not set in .env")
    exit(1)

w3 = Web3(Web3.HTTPProvider(RPC_URL))
print(f"✅ RPC connected: {w3.is_connected()} | URL: {RPC_URL}")

# Addresses
USDT_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDT on Polygon
WETH_ADDRESS = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

daily_loss_today = 0.0

async def run_real_trade():
    global daily_loss_today

    if daily_loss_today >= MAX_DAILY_LOSS_USDT:
        print(f"🛑 DAILY LOSS LIMIT REACHED ({daily_loss_today:.2f}/{MAX_DAILY_LOSS_USDT} USDT). Trading paused today.")
        return

    # SIM Alignment Check
    try:
        with open("skills/autonomous-revenue-engine/capital.json") as f:
            sim_data = json.load(f)
            sim_capital = sim_data.get("capital", 0)
            sim_positive = sim_capital > SIM_CONFIDENCE_THRESHOLD
        print(f"✅ SIM Confidence: {'Strong' if sim_positive else 'Low'} (~{sim_capital/1000:.0f}k)")
    except:
        sim_positive = True

    if not sim_positive:
        print("⏸️ SIM confidence low - skipping baseline trade")
        return

       trade_size = TRADE_SIZE_USDT   # Force config value here

    print(f"""
══════════════════════════════════════
🚀 v2 TRADE (SIM-Aligned)
Strategy : {"Baseline" if "baseline" in ACTIVE_STRATEGIES else "Polymarket"}
Wallet : {WALLET_ADDRESS[:10]}...
Trade Size : {trade_size:.2f} USDT → WETH   ← from config_real.py (forced)
Daily Loss : {daily_loss_today:.2f}/{MAX_DAILY_LOSS_USDT} USDT
Min Edge  : {MIN_EDGE_PCT}%
══════════════════════════════════════
""")

    from swap_utils import execute_usdt_to_weth_swap
    tx_hash = await execute_usdt_to_weth_swap(w3, WALLET_ADDRESS, PRIVATE_KEY, trade_size)

    if tx_hash:
        daily_loss_today += 0.08  # approximate fee
        print(f"✅ Baseline trade completed. Tx: {tx_hash}")
    else:
        print("❌ Baseline trade failed")

if __name__ == "__main__":
    asyncio.run(run_real_trade())
