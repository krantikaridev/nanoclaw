import os
import time
import sys
import os
import time
import sys
import asyncio
import os
import time
import sys

# Simple lock to prevent double execution in the same cycle
import os
import time
import sys
from web3 import Web3
from dotenv import load_dotenv
import os
import time
import json
from datetime import datetime

load_dotenv()

# === CONFIG FROM ENV (modular, weekday tweaks easy) ===
WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = os.getenv("RPC", "https://polygon.drpc.org")
USDT = os.getenv("USDT")
WETH = os.getenv("WETH")
ROUTER = os.getenv("ROUTER")

MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", 2.0))
MAX_GAS_GWEI = int(os.getenv("MAX_GAS_GWEI", 90))  # temporary bump
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 15))
USDT_SEED_TARGET = float(os.getenv("USDT_SEED_TARGET", 10.0))
REBALANCE_WETH_AMOUNT = float(os.getenv("REBALANCE_WETH_AMOUNT", 0.004))  # ~$9-10

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

def get_current_gas_gwei():
    try:
        # Reliable fallback using PolygonScan gas tracker
        import requests
        r = requests.get("https://polygonscan.com/gastracker", timeout=10).text
        # Simple parse for standard gas (robust against API changes)
        if "Standard" in r:
            gas_str = r.split("Standard")[1].split("Gwei")[0].strip().split()[-1]
            return int(float(gas_str))
    except:
        pass
    return 80  # safe static fallback (never 999)

def get_pol_balance():
    pol_contract = "0x0000000000000000000000000000000000001010"  # POL native
    return w3.eth.get_balance(WALLET) / 10**18
    
def has_pending_transactions():
    try:
        latest = w3.eth.get_transaction_count(WALLET, "latest")
        pending = w3.eth.get_transaction_count(WALLET, "pending")
        if pending > latest:
            print(f"⏳ {pending - latest} pending transaction(s) detected — skipping rebalance this cycle")
            return True
        return False
    except:
        return False
        
def should_run_cycle(state):
    now = time.time()
    if now - state.get("last_run", 0) < COOLDOWN_MINUTES * 60:
        print(f"⏳ Cooldown active ({COOLDOWN_MINUTES} min) — skipping")
        return False
    gas = get_current_gas_gwei()
    if gas > MAX_GAS_GWEI:
        print(f"⛽ Gas too high ({gas} Gwei > {MAX_GAS_GWEI}) — skipping cycle")
        return False
    pol = get_pol_balance()
    if pol < 2.0:
        print(f"⚠️ POL GAS CRITICAL ({pol:.2f} < 2.0) — TOP UP MANUALLY & skipping")
        return False
    return True

async def approve_and_swap(amount_in: int, direction="USDT_TO_WETH"):
    """Fixed version with dynamic gas + replacement safety"""
    if direction == "USDT_TO_WETH":
        token_in = USDT
        token_out = WETH
        amount = amount_in
    else:  # WETH_TO_USDT
        token_in = WETH
        token_out = USDT
        amount = int(REBALANCE_WETH_AMOUNT * 10**18)   # ~0.004 WETH

    print(f"🔄 Starting {direction} | Amount: {amount} | Gas multiplier active")

    # Dynamic safe gas price (30% higher for replacement txs)
    current_gas_wei = w3.eth.gas_price
    safe_gas_wei = int(current_gas_wei * 1.3)   # GAS_PRICE_MULTIPLIER = 1.3
    print(f"   Using gasPrice: {safe_gas_wei // 10**9} Gwei (30% bump)")

    # Approve
    contract_in = w3.eth.contract(address=token_in, abi=[{
        "inputs": [{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
        "name":"approve",
        "outputs": [{"name":"","type":"bool"}],
        "stateMutability":"nonpayable",
        "type":"function"
    }])

    approve_tx = contract_in.functions.approve(ROUTER, amount).build_transaction({
        'from': WALLET,
        'gas': 100000,
        'gasPrice': safe_gas_wei,
        'nonce': w3.eth.get_transaction_count(WALLET, 'pending'),   # IMPORTANT for replacement
    })

    signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
    approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    print(f"✅ Approve Tx ({direction}): {approve_hash.hex()}")
    await asyncio.sleep(15)

    # Swap
    router = w3.eth.contract(address=ROUTER, abi=[{
        "inputs": [{"components": [
            {"name":"tokenIn","type":"address"},
            {"name":"tokenOut","type":"address"},
            {"name":"fee","type":"uint24"},
            {"name":"recipient","type":"address"},
            {"name":"deadline","type":"uint256"},
            {"name":"amountIn","type":"uint256"},
            {"name":"amountOutMinimum","type":"uint256"},
            {"name":"sqrtPriceLimitX96","type":"uint160"}
        ], "name":"params","type":"tuple"}],
        "name":"exactInputSingle",
        "outputs": [{"name":"","type":"uint256"}],
        "stateMutability":"payable",
        "type":"function"
    }])

    params = {
        "tokenIn": token_in,
        "tokenOut": token_out,
        "fee": 500,
        "recipient": WALLET,
        "deadline": int(datetime.now().timestamp()) + 600,
        "amountIn": amount,
        "amountOutMinimum": 0,
        "sqrtPriceLimitX96": 0
    }

    tx = router.functions.exactInputSingle(params).build_transaction({
        'from': WALLET,
        'gas': 400000,
        'gasPrice': safe_gas_wei,
        'nonce': w3.eth.get_transaction_count(WALLET, 'pending'),
    })

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ REAL TX HASH ({direction}): {tx_hash.hex()}")
    print(f"https://polygonscan.com/tx/{tx_hash.hex()}")

async def auto_rebalance():
    usdt_balance = w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}]).functions.balanceOf(WALLET).call() / 10**6
    if usdt_balance < 5.0:
        print(f"🔄 Auto-rebalance: USDT low ({usdt_balance:.2f}). Swapping ~$15 WETH → USDT")
        await approve_and_swap(0, direction="WETH_TO_USDT")  # amount ignored for WETH side
    else:
        print(f"✅ USDT seed healthy ({usdt_balance:.2f})")

async def main():
    state = load_state()
    usdt_balance = w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}]).functions.balanceOf(WALLET).call() / 10**6
    print(f"[{datetime.now()}] Real USDT: {usdt_balance:.2f} | POL: {get_pol_balance():.2f}")

    if not should_run_cycle(state):
        return

    if usdt_balance < MIN_TRADE_USD:
        if has_pending_transactions():
            return
        print("⚠️ Not enough USDT for min trade — triggering rebalance")
        await auto_rebalance()
        return

    trade_amount = int(max(MIN_TRADE_USD * 1_000_000, 2_000_000))
    print(f"🚀 Executing larger bet: ${trade_amount/1_000_000:.2f} USDT → WETH")
    await approve_and_swap(trade_amount)

    state["last_run"] = time.time()
    save_state(state)
    await asyncio.sleep(2)  # small delay
    send_telegram(f"Cycle finished. USDT: {usdt_balance:.2f} | POL: {get_pol_balance():.2f} | WETH dominant. Next cycle in ~{COOLDOWN_MINUTES} min.")
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min | Guardrails active (min ${MIN_TRADE_USD}, gas <{MAX_GAS_GWEI}, cooldown {COOLDOWN_MINUTES}min)")

def send_telegram(message):
    try:
        import requests
        url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage"
        payload = {
            "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
            "text": f"[{datetime.now().strftime('%H:%M')}] NanoClaw:\n{message}"
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.json().get("ok"):
            print("✅ Telegram notification sent")
        else:
            print("❌ Telegram failed:", r.json())
    except Exception as e:
        print("Telegram send failed (non-critical):", str(e))

if __name__ == "__main__":
    asyncio.run(main())


# Simple lock to prevent double execution in the same cycle
LOCK_FILE = "/tmp/nanoclaw.lock"
if os.path.exists(LOCK_FILE) and (time.time() - os.path.getmtime(LOCK_FILE) < 300):  # 5 min
    print("⛔ Lock active — skipping to avoid double-run")
    sys.exit(0)
open(LOCK_FILE, 'w').close()
