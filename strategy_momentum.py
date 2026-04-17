#!/usr/bin/env python3
"""
Nanoclaw v2 - Momentum Baseline Strategy (Madan Pune)
Simple momentum-based trade when SIM is strong
"""

import asyncio
from datetime import datetime
from dotenv import load_dotenv
from web3 import Web3
import json

load_dotenv()

try:
    from config_real import TRADE_SIZE_USDT, MAX_DAILY_LOSS_USDT, MIN_EDGE_PCT, SIM_CONFIDENCE_THRESHOLD, ACTIVE_STRATEGIES, WALLET_ADDRESS, RPC_URL
except ImportError:
    TRADE_SIZE_USDT = 2.0
    MAX_DAILY_LOSS_USDT = 10.0
    MIN_EDGE_PCT = 3.0
    SIM_CONFIDENCE_THRESHOLD = 200000
    ACTIVE_STRATEGIES = ["baseline", "polymarket"]
    WALLET_ADDRESS = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
    RPC_URL = "https://polygon.drpc.org"

PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

daily_loss_today = 0.0

async def run_real_trade():
    global daily_loss_today

    if daily_loss_today >= MAX_DAILY_LOSS_USDT:
        print(f"🛑 DAILY LOSS LIMIT REACHED. Paused.")
        return

    # Strong SIM Check for Momentum
    try:
        with open("skills/autonomous-revenue-engine/capital.json") as f:
            sim_data = json.load(f)
            sim_capital = sim_data.get("capital", 0)
            sim_positive = sim_capital > SIM_CONFIDENCE_THRESHOLD * 1.1
        print(f"✅ Momentum SIM Check: {'Strong' if sim_positive else 'Weak'} (~{sim_capital/1000:.0f}k)")
    except:
        sim_positive = False

    if not sim_positive:
        print("⏸️ SIM not strong enough for momentum strategy - skipping")
        return

    print(f"""
══════════════════════════════════════
🚀 v2 MOMENTUM BASELINE TRADE
Wallet : {WALLET_ADDRESS[:10]}...
Trade Size : {TRADE_SIZE_USDT:.2f} USDT → WETH
══════════════════════════════════════
""")

    from swap_utils import execute_usdt_to_weth_swap
    tx_hash = await execute_usdt_to_weth_swap(w3, WALLET_ADDRESS, PRIVATE_KEY, TRADE_SIZE_USDT)

    if tx_hash:
        daily_loss_today += 0.08
        print(f"✅ Momentum trade completed. Tx: {tx_hash}")
    else:
        print("❌ Momentum trade failed")

if __name__ == "__main__":
    asyncio.run(run_real_trade())
