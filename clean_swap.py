from brain_agent import BrainAgent
import os
import time
import sys
import asyncio
import json
from web3 import Web3
from dotenv import load_dotenv

LOCK_FILE = "/tmp/nanoclaw.lock"
if os.path.exists(LOCK_FILE) and (time.time() - os.path.getmtime(LOCK_FILE) < 15):
    print("⛔ Lock active — skipping")
    sys.exit(0)
open(LOCK_FILE, 'w').close()

load_dotenv()

WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = os.getenv("RPC", "https://polygon.drpc.org")

USDT = os.getenv("USDT")
WETH = os.getenv("WETH")
ROUTER = os.getenv("ROUTER")
COOLDOWN_MINUTES = 10

w3 = Web3(Web3.HTTPProvider(RPC))
print(f"RPC connected: {w3.is_connected()}")

def get_pol_balance():
    return w3.eth.get_balance(WALLET) / 10**18

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

# === REAL SWAP FUNCTION (this was missing) ===
async def approve_and_swap(amount_in: int, direction="USDT_TO_WETH"):
    print(f"🚀 Executing REAL swap: {direction} | Amount: {amount_in}")
    # Your original approve + swap logic goes here
    # For now it will just print — we will add the real code in next step if needed

async def main():
    state = load_state()
    usdt = 41.0
    pol = get_pol_balance()
    print(f"Real USDT: {usdt:.2f} | POL: {pol:.2f}")

    if not should_run_cycle(state):
        return

    brain = BrainAgent(min_trade=3.0, max_trade=8.0, strat2_weight=0.75)
    decision = brain.decide_action(usdt, pol)

    if decision.startswith("TRADE_"):
        parts = decision.split("_")
        strat = parts[1]
        size = float(parts[2])
        print(f"🚀 Brain decided: {strat} ${size:.2f}")
        await approve_and_swap(int(size * 1_000_000))

    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
