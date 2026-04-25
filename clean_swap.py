from v25_protection import check_exit_conditions, record_buy, get_live_wmatic_price
from v25_copy_trading import get_target_wallets, get_copy_ratio
from brain_agent import BrainAgent
import os
import time
import sys
import asyncio
import json
from web3 import Web3
from dotenv import load_dotenv
from constants import WALLET, USDT, WMATIC, ROUTER, ROUTER_ABI, ERC20_ABI
from swap_executor import approve_and_swap

load_dotenv()

LOCK_FILE = "/tmp/nanoclaw.lock"
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 7))
COPY_COOLDOWN_MINUTES = int(os.getenv("COPY_COOLDOWN_MINUTES", 2))

w3 = Web3(Web3.HTTPProvider(os.getenv("RPC")))

def get_token_balance(token_address: str, decimals: int = 6) -> float:
    try:
        contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return contract.functions.balanceOf(WALLET).call() / (10 ** decimals)
    except:
        return 0.0

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

async def main():
    state = load_state()
    usdt_balance = get_token_balance(USDT, 6)
    wmatic_balance = get_token_balance(WMATIC, 18)
    pol = get_pol_balance()

    print(f"Real USDT: {usdt_balance:.2f} | WMATIC: {wmatic_balance:.2f} | POL: {pol:.2f}")

    if os.path.exists(LOCK_FILE) and (time.time() - os.path.getmtime(LOCK_FILE) < 15):
        print("⛔ Lock active — skipping")
        return

    open(LOCK_FILE, 'w').close()

    if not (time.time() - state.get("last_run", 0) > COOLDOWN_MINUTES * 60):
        print(f"⏳ Cooldown active — skipping")
        return

    # === V2.5.1 Protection Check ===
    should_force_sell, reason = check_exit_conditions()
    if should_force_sell:
        direction = "WMATIC_TO_USDT"
        amount_in = int(wmatic_balance * 0.28 * 1e18)
        print(f"🛡️ PROTECTION TRIGGERED: {reason}")
    else:
        # === 80/20 Decision ===
        if os.getenv("COPY_TRADING_ENABLED", "true").lower() == "true" and get_target_wallets():
            print("🔄 COPY TRADING MODE (20%) - TODO: Implement monitor")
            # Placeholder for copy logic - we will expand this next
            direction = "USDT_TO_WMATIC"
            trade_size = max(15.0, min(35.0, usdt_balance * 0.20))
        else:
            print("🔄 MAIN STRATEGY MODE (80%)")
            trade_size = max(15.0, min(35.0, usdt_balance * 0.28))
            wmatic_value_usd = wmatic_balance * get_live_wmatic_price()

            if usdt_balance < 40:
                direction = "WMATIC_TO_USDT"
                amount_in = int(wmatic_balance * 0.30 * 1e18)
            elif wmatic_value_usd > 70:
                direction = "WMATIC_TO_USDT"
                amount_in = int(wmatic_balance * 0.30 * 1e18)
            elif wmatic_value_usd < 40 and wmatic_balance > 50:
                direction = "WMATIC_TO_USDT"
                amount_in = int(wmatic_balance * 0.28 * 1e18)
            else:
                direction = "USDT_TO_WMATIC"
                amount_in = int(trade_size * 1_000_000)

        if direction == "USDT_TO_WMATIC":
            current_price = get_live_wmatic_price()
            record_buy(current_price, trade_size, "pending")

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
