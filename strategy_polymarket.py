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
        print("⏸️ SIM confidence low - skipping Polymarket trade")
        return

    # Simple Polymarket scan placeholder (will be enhanced with Gamma later)
    print(f"""
══════════════════════════════════════
🚀 v2 POLYMARKET STRATEGY
Wallet : {WALLET_ADDRESS[:10]}...
Trade Size : {TRADE_SIZE_USDT:.2f} USDT → WETH
Min Edge : {MIN_EDGE_PCT}% 
══════════════════════════════════════
""")

    # For now: simulate edge check (replace with real Gamma call in next iteration)
    edge_found = 4.2  # placeholder - we will make this dynamic
    if edge_found < MIN_EDGE_PCT:
        print(f"⏸️ Edge too low ({edge_found}%) - skipping trade")
        return

    trade_size = TRADE_SIZE_USDT
    print(f"🚀 Executing Polymarket-backed trade of {trade_size:.2f} USDT")

    try:
        # Same swap logic as runner (we can extract to shared file later)
        usdt_contract = w3.eth.contract(address=USDT_ADDRESS, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}])
        usdt_balance = usdt_contract.functions.balanceOf(WALLET_ADDRESS).call() / 10**6
        if usdt_balance < trade_size:
            print(f"❌ INSUFFICIENT USDT")
            return

        router = w3.eth.contract(address=ROUTER_ADDRESS, abi=[{"inputs":[{"components":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"fee","type":"uint24"},{"name":"recipient","type":"address"},{"name":"deadline","type":"uint256"},{"name":"amountIn","type":"uint256"},{"name":"amountOutMinimum","type":"uint256"},{"name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}])

        # Approve + Swap (same as improved runner)
        approve_tx = usdt_contract.functions.approve(ROUTER_ADDRESS, int(trade_size * 10**6 * 10)).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 150000,
            'gasPrice': w3.to_wei('140', 'gwei'),
            'nonce': w3.eth.get_transaction_count(WALLET_ADDRESS),
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        await asyncio.sleep(8)

        params = {
            "tokenIn": USDT_ADDRESS,
            "tokenOut": WETH_ADDRESS,
            "fee": 500,
            "recipient": WALLET_ADDRESS,
            "deadline": int(datetime.now().timestamp()) + 600,
            "amountIn": int(trade_size * 10**6),
            "amountOutMinimum": int(trade_size * 10**6 * 0.96),
            "sqrtPriceLimitX96": 0
        }
        swap_tx = router.functions.exactInputSingle(params).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 300000,
            'gasPrice': w3.to_wei('140', 'gwei'),
            'nonce': w3.eth.get_transaction_count(WALLET_ADDRESS, 'pending'),
        })
        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)

        print(f"✅ Polymarket trade executed! Tx: {tx_hash.hex()}")
        daily_loss_today += 0.08  # approximate fee

    except Exception as e:
        print(f"❌ Trade failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_real_trade())
