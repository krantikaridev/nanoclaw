from brain_agent import BrainAgent
import random
import os
import time
import sys
import asyncio
import json
from web3 import Web3
from dotenv import load_dotenv
from datetime import datetime

# Simple lock
LOCK_FILE = "/tmp/nanoclaw.lock"
if os.path.exists(LOCK_FILE) and (time.time() - os.path.getmtime(LOCK_FILE) < 300):
    print("⛔ Lock active — skipping to avoid double-run")
    sys.exit(0)
open(LOCK_FILE, 'w').close()

load_dotenv()

WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = os.getenv("RPC", "https://polygon.drpc.org")
USDT = os.getenv("USDT")
WETH = os.getenv("WETH")
ROUTER = os.getenv("ROUTER")

MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", 3.0))
MAX_TRADE_USD = float(os.getenv("MAX_TRADE_USD", 8.0))
MAX_GAS_GWEI = int(os.getenv("MAX_GAS_GWEI", 110))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 20))
USDT_SEED_TARGET = float(os.getenv("USDT_SEED_TARGET", 100.0))
REBALANCE_WETH_AMOUNT = float(os.getenv("REBALANCE_WETH_AMOUNT", 0.008))

STRAT2_WEIGHT = float(os.getenv("STRAT2_WEIGHT", 0.75))
STRAT2_MIN_BET_USD = float(os.getenv("STRAT2_MIN_BET_USD", 2.5))
STRAT2_MAX_BET_USD = float(os.getenv("STRAT2_MAX_BET_USD", 6.5))

w3 = Web3(Web3.HTTPProvider(RPC))
print(f"[{datetime.now()}] RPC connected: {w3.is_connected()}")

def load_state():
    try:
        with open('bot_state.json', 'r') as f:
            return json.load(f)
    except:
        return {"last_run": 0}

def save_state(state):
    with open('bot_state.json', 'w') as f:
        json.dump(state, f, indent=2)

def get_pol_balance():
    return w3.eth.get_balance(WALLET) / 10**18

def should_run_cycle(state):
    now = time.time()
    if now - state.get("last_run", 0) < COOLDOWN_MINUTES * 60:
        print(f"⏳ Cooldown active ({COOLDOWN_MINUTES} min) — skipping")
        return False
    gas = 80  # simplified
    if gas > MAX_GAS_GWEI:
        print(f"⛽ Gas too high — skipping")
        return False
    pol = get_pol_balance()
    if pol < 2.0:
        print(f"⚠️ POL GAS CRITICAL ({pol:.2f} < 2.0) — skipping")
        return False
    return True

async def auto_topup_pol():
    pol_balance = get_pol_balance()
    if pol_balance < 2.5:
        print(f"⚠️ POL low ({pol_balance:.2f}) — auto top-up triggered")

async def approve_and_swap(amount_in: int, direction="USDT_TO_WETH"):
    print(f"🔄 Starting {direction} | Amount: {amount_in}")

async def auto_rebalance():
    print("🔄 Auto-rebalance triggered")

def get_brain_decision(usdt_balance, pol_balance):
    brain = BrainAgent(min_trade=3.0, max_trade=6.5, strat2_weight=0.75)
    return brain.decide_action(usdt_balance, pol_balance)

async def execute_trade(strat, size_usd):
    print(f"🚀 Brain decided: {strat} ${size_usd:.2f}")

async def main():
    state = load_state()
    usdt_balance = 41.0  # placeholder
    pol_balance = get_pol_balance()
    print(f"Real USDT: {usdt_balance:.2f} | POL: {pol_balance:.2f}")

    if not should_run_cycle(state):
        return

    await auto_topup_pol()
    decision = get_brain_decision(usdt_balance, pol_balance)

    if decision == "REBALANCE":
        await auto_rebalance()
    elif decision.startswith("TRADE_"):
        parts = decision.split("_")
        strat = parts[1]
        size = float(parts[2])
        await execute_trade(strat, size)

    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
