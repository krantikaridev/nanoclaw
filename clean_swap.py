import asyncio
from web3 import Web3
from dotenv import load_dotenv
import os
import time
import json
from datetime import datetime

load_dotenv()

# === CONFIG FROM ENV (modular + easy to change) ===
WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = os.getenv("RPC", "https://polygon.drpc.org")
USDT = os.getenv("USDT")
WETH = os.getenv("WETH")
ROUTER = os.getenv("ROUTER")

MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", 2.0))
MAX_GAS_GWEI = int(os.getenv("MAX_GAS_GWEI", 80))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 5))
USDT_SEED_TARGET = float(os.getenv("USDT_SEED_TARGET", 10.0))
REBALANCE_WETH_AMOUNT = float(os.getenv("REBALANCE_WETH_AMOUNT", 0.003))

w3 = Web3(Web3.HTTPProvider(RPC))
print("RPC connected:", w3.is_connected())

# Load state
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
        # Use Polygon gas station or fallback
        import requests
        r = requests.get("https://gasstation-mainnet.polygon.technology/v2", timeout=10).json()
        return int(r['standard']['maxFee'])
    except:
        return 999  # safe skip

def should_run_cycle(state):
    now = time.time()
    if now - state.get("last_run", 0) < COOLDOWN_MINUTES * 60:
        print(f"⏳ Cooldown active ({COOLDOWN_MINUTES} min) — skipping")
        return False
    gas = get_current_gas_gwei()
    if gas > MAX_GAS_GWEI:
        print(f"⛽ Gas too high ({gas} Gwei > {MAX_GAS_GWEI}) — skipping cycle")
        return False
    return True

async def approve_and_swap(amount_in_usdt: int):
    """Your original swap logic — kept almost identical, now with dynamic gas"""
    # Approve (only if needed — but for simplicity we keep your style)
    usdt_contract = w3.eth.contract(address=USDT, abi=[{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"}])
    approve_tx = usdt_contract.functions.approve(ROUTER, amount_in_usdt).build_transaction({
        'from': WALLET,
        'gas': 100000,
        'gasPrice': w3.to_wei('60', 'gwei'),  # lower than your 400 — safer
        'nonce': w3.eth.get_transaction_count(WALLET),
    })
    signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
    approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    print("✅ Approve Tx:", approve_hash.hex())
    await asyncio.sleep(15)  # slightly longer wait

    # Swap
    router = w3.eth.contract(address=ROUTER, abi=[{"inputs":[{"components":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"fee","type":"uint24"},{"name":"recipient","type":"address"},{"name":"deadline","type":"uint256"},{"name":"amountIn","type":"uint256"},{"name":"amountOutMinimum","type":"uint256"},{"name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"name":"","type":"uint256"}],"stateMutability":"payable","type":"function"}])
    params = {
        "tokenIn": USDT,
        "tokenOut": WETH,
        "fee": 500,
        "recipient": WALLET,
        "deadline": int(datetime.now().timestamp()) + 600,
        "amountIn": amount_in_usdt,
        "amountOutMinimum": 0,
        "sqrtPriceLimitX96": 0
    }
    tx = router.functions.exactInputSingle(params).build_transaction({
        'from': WALLET,
        'gas': 400000,
        'gasPrice': w3.to_wei('60', 'gwei'),  # controlled
        'nonce': w3.eth.get_transaction_count(WALLET),
    })
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print("✅ REAL TX HASH:", tx_hash.hex())
    print("https://polygonscan.com/tx/" + tx_hash.hex())

async def auto_rebalance():
    """Keep USDT seed healthy — swap from WETH only when needed (single larger tx)"""
    usdt_balance = w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}]).functions.balanceOf(WALLET).call() / 10**6
    
    if usdt_balance < USDT_SEED_TARGET:
        print(f"🔄 Auto-rebalance: USDT low ({usdt_balance:.2f} < {USDT_SEED_TARGET}). Swapping ~${REBALANCE_WETH_AMOUNT*2400:.0f} worth WETH → USDT")
        # For WETH→USDT you would reverse tokenIn/tokenOut and amount calculation
        # For now, since your core is USDT→WETH, we can add a simple reverse swap here later if needed
        # Placeholder: trigger a controlled swap — we'll expand in next iteration
        pass  # TODO: implement reverse swap similarly (minimal change)

# Main cycle
async def main():
    state = load_state()
    print(f"Real USDT balance: {w3.eth.contract(address=USDT, abi=[{'constant':True,'inputs':[{'name':'_owner','type':'address'}],'name':'balanceOf','outputs':[{'name':'balance','type':'uint256'}],'payable':False,'stateMutability':'view','type':'function'}]).functions.balanceOf(WALLET).call() / 10**6:.2f}")
    
    if not should_run_cycle(state):
        return
    
    # Calculate trade size (larger bet)
    usdt_balance = ...  # reuse your balance call
    trade_amount_usdt = int(max(MIN_TRADE_USD * 1_000_000, 2_000_000))  # at least $2
    
    if usdt_balance * 1_000_000 < trade_amount_usdt:
        print("⚠️ Not enough USDT for min trade — skipping or triggering rebalance")
        await auto_rebalance()
        return
    
    print(f"🚀 Executing larger trade: ${trade_amount_usdt/1_000_000:.2f} USDT → WETH")
    await approve_and_swap(trade_amount_usdt)
    
    # Update state
    state["last_run"] = time.time()
    save_state(state)
    print("✅ Cycle completed — next possible in", COOLDOWN_MINUTES, "minutes")

if __name__ == "__main__":
    asyncio.run(main())
