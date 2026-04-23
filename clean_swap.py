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

# ERC20 ABI for balance and approve
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]
QUICKSWAP_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]
def get_pol_balance():
    return w3.eth.get_balance(WALLET) / 10**18

def get_token_balance(token_address: str, decimals: int = 6) -> float:
    """Get balance of any ERC20 token"""
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        balance_wei = contract.functions.balanceOf(WALLET).call()
        balance = balance_wei / (10 ** decimals)
        return balance
    except Exception as e:
        print(f"❌ Error reading token balance: {e}")
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

async def approve_and_swap(amount_in: int, direction="USDT_TO_WETH"):
    """Execute approve and swap transactions with error handling"""
    print(f"🚀 Executing REAL swap: {direction} | Amount: {amount_in}")
    
    try:
        if direction == "USDT_TO_WETH":
            token_in = USDT
            token_out = WETH
        else:
            token_in = WETH
            token_out = USDT

        # Checksum addresses
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)
        router = Web3.to_checksum_address(ROUTER)

        # ERC20 ABI
        erc20_abi = [
            {
                "constant": False,
                "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function",
            }
        ]

        # Get nonce
        nonce = w3.eth.get_transaction_count(WALLET)

        # === APPROVE ===
        approve_contract = w3.eth.contract(address=token_in, abi=erc20_abi)
        approve_tx = approve_contract.functions.approve(router, amount_in).build_transaction({
            'from': WALLET,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': w3.eth.gas_price * 13 // 10,
            'chainId': 137  # Polygon chainId
        })
        
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        # For web3.py 7.x, use:
        approve_hash = w3.eth.send_raw_transaction(signed_approve.rawTransaction)
        print(f"✅ Approve Tx: {approve_hash.hex()}")
        
        # Wait for approve
        receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=300)
        if receipt['status'] == 0:
            print("❌ Approve failed!")
            return False
        print("✅ Approve confirmed!")

        await asyncio.sleep(2)

        # === SWAP ===
        # QuickSwap Router ABI
        router_abi = [
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]

        swap_contract = w3.eth.contract(address=router, abi=router_abi)
        path = [token_in, token_out]
        
        nonce_swap = w3.eth.get_transaction_count(WALLET)
        swap_tx = swap_contract.functions.swapExactTokensForTokens(
            amount_in, 0, path, WALLET, int(time.time()) + 300
        ).build_transaction({
            'from': WALLET,
            'nonce': nonce_swap,
            'gas': 200000,
            'gasPrice': w3.eth.gas_price * 13 // 10,
            'chainId': 137
        })
        
        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        swap_hash = w3.eth.send_raw_transaction(signed_swap.rawTransaction)
        print(f"✅ REAL TX HASH: {swap_hash.hex()}")
        print(f"https://polygonscan.com/tx/{swap_hash.hex()}")
        
        # Wait for swap
        receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=300)
        if receipt['status'] == 0:
            print("❌ Swap failed!")
            return False
        print("✅ Swap confirmed!")
        return True
        
    except Exception as e:
        print(f"❌ Error in approve_and_swap: {e}")
        import traceback
        traceback.print_exc()
        return False
    
async def main():
    state = load_state()
    
    # Read ACTUAL token balance instead of hardcoding
    usdt = get_token_balance(USDT, decimals=6)  # USDT has 6 decimals
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
        
        # Execute swap with error handling
        success = await approve_and_swap(int(size * 1_000_000))
        if not success:
            print("⚠️ Swap failed, not updating state")
            return

    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
