from brain_agent import BrainAgent
import os
import time
import sys
import asyncio
import json
from web3 import Web3
from dotenv import load_dotenv
from constants import WALLET, USDT, WETH, ROUTER, ROUTER_ABI, ERC20_ABI
from swap_executor import approve_and_swap

LOCK_FILE = "/tmp/nanoclaw.lock"
if os.path.exists(LOCK_FILE) and (time.time() - os.path.getmtime(LOCK_FILE) < 15):
    print("⛔ Lock active — skipping")
    sys.exit(0)
open(LOCK_FILE, 'w').close()

load_dotenv()

COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 7))

w3 = Web3(Web3.HTTPProvider(os.getenv("RPC")))
print(f"RPC connected: {w3.is_connected()}")

def get_pol_balance():
    return w3.eth.get_balance(WALLET) / 10**18

def get_token_balance(token_address: str, decimals: int = 6) -> float:
    if not token_address:
        return 0.0
    try:
        contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return contract.functions.balanceOf(WALLET).call() / (10 ** decimals)
    except:
        return 0.0

def load_state():
    try:
        with open('bot_state.json', 'r') as f:
            return json.load(f)
    except:
        return {"last_run": 0}

def save_state(state):
    with open('bot_state.json', 'w') as f:
        json.dump(state, f, indent=2)

def should_run_cycle(state):
    now = time.time()
    if now - state.get("last_run", 0) < COOLDOWN_MINUTES * 60:
        print(f"⏳ Cooldown active ({COOLDOWN_MINUTES} min) — skipping")
        return False
    if get_pol_balance() < 2.0:
        print("⚠️ POL low — skipping")
        return False
    return True

async def main():
    state = load_state()

    usdt_balance = get_token_balance(USDT, decimals=6)
    pol = get_pol_balance()
    print(f"Real USDT: {usdt_balance:.2f} | POL: {pol:.2f}")

    if not should_run_cycle(state):
        return

    brain = BrainAgent(min_trade=3.0, max_trade=8.0, strat2_weight=0.75)
    decision = brain.decide_action(usdt_balance, pol)

    if decision.startswith("TRADE_"):
        trade_size = max(15.0, min(25.0, usdt_balance * 0.25))
        print(f"💰 Fresh USDT: ${usdt_balance:.2f} → Trade size: ${trade_size:.2f}")

        weth_balance = get_token_balance(WETH, decimals=18)
        weth_value_usd = weth_balance * 2350

        if weth_value_usd > 50:
            direction = "WETH_TO_USDT"
            amount_in = int(weth_balance * 0.35 * 1e18)
            print(f"🔄 Selling WETH → USDT (${weth_value_usd:.2f} in WETH)")
        else:
            direction = "USDT_TO_WETH"
            amount_in = int(trade_size * 1_000_000)
            print(f"🔄 Buying WETH with USDT")

        tx_hash = await approve_and_swap(w3, os.getenv("POLYGON_PRIVATE_KEY"), amount_in, direction=direction)
        if tx_hash:
            print("✅ Swap executed successfully!")
        else:
            print("⚠️ Swap failed")

    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
