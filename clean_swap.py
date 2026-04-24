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
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 10))

w3 = Web3(Web3.HTTPProvider(RPC))
print(f"RPC connected: {w3.is_connected()}")

# === PERFORMANCE TRACKER ===
trade_history = []      # List of dicts: {profitable, fee, timestamp, trade_size}
total_fees_paid = 0.0
starting_usdt = 120.0    # Change this when you add more capital

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
    """Get balance of any ERC20 token with error handling"""
    if not token_address:
        return 0.0
    try:
        checksum_addr = Web3.to_checksum_address(token_address)
        contract = w3.eth.contract(address=checksum_addr, abi=ERC20_ABI)
        balance_wei = contract.functions.balanceOf(WALLET).call()
        balance = balance_wei / (10 ** decimals)
        return balance
    except Exception as e:
        print(f"⚠️  Warning: Could not read balance for {token_address[:10]}... ({str(e)[:50]})")
        return 0.0

def load_state():
    try:
        with open('bot_state.json', 'r') as f:
            return json.load(f)
    except:
        return {"last_run": 0, "trades": []}

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

# === PERFORMANCE TRACKER (Simple & Persistent) ===
def load_performance():
    try:
        with open("performance.json", "r") as f:
            return json.load(f)
    except:
        return {"trades": [], "total_fees": 0.0}

def save_performance(data):
    with open("performance.json", "w") as f:
        json.dump(data, f, indent=2)

def update_performance(was_profitable: bool, fee_usd: float = 0.8, trade_size: float = 0.0):
    data = load_performance()
    data["trades"].append({
        "profitable": was_profitable,
        "fee": fee_usd,
        "trade_size": trade_size,
        "timestamp": time.time()
    })
    if len(data["trades"]) > 50:
        data["trades"].pop(0)
    data["total_fees"] += fee_usd
    save_performance(data)

def print_performance():
    data = load_performance()
    trades = data.get("trades", [])
    if not trades:
        print("📊 No trades yet - waiting for data...")
        return
    wins = sum(1 for t in trades if t.get("profitable", False))
    total = len(trades)
    win_rate = (wins / total) * 100 if total > 0 else 0
    total_fees = data.get("total_fees", 0.0)
    total_traded = sum(t.get("trade_size", 0) for t in trades)
    estimated_profit = (wins * 6.0) - total_fees
    print(f"┌─ 📊 PERFORMANCE METRICS (Last {total} trades)")
    print(f"├─ Win Rate: {win_rate:.1f}% ({wins}/{total})")
    print(f"├─ Total Traded: ${total_traded:.2f}")
    print(f"├─ Fees Paid: ${total_fees:.2f}")
    print(f"├─ Est. Gross PNL: ${estimated_profit:.2f}")
    print(f"└─ Remaining Capital: ${124.95 + estimated_profit:.2f}")

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
            'gasPrice': w3.eth.gas_price * 12 // 10,
            'chainId': 137  # Polygon chainId
        })
        
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"✅ Approve Tx: {approve_hash.hex()}")
        
        # Wait for approve
        receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=300)
        if receipt['status'] == 0:
            print("❌ Approve failed!")
            return None
        print("✅ Approve confirmed!")

        await asyncio.sleep(2)

        # === SWAP ===
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
            'gasPrice': w3.eth.gas_price * 12 // 10,
            'chainId': 137
        })
        
        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
        print(f"✅ REAL TX HASH: {swap_hash.hex()}")
        print(f"https://polygonscan.com/tx/{swap_hash.hex()}")
        
        # Wait for swap
        receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=300)
        if receipt['status'] == 0:
            print("❌ Swap failed!")
            return None
        print("✅ Swap confirmed!")
        
        # Return the transaction hash for future tracking
        return swap_hash.hex()
        
    except Exception as e:
        print(f"❌ Error in approve_and_swap: {e}")
        import traceback
        traceback.print_exc()
        return None
    
async def main():
    state = load_state()
    
    # Read ACTUAL USDT balance BEFORE swap (WETH is optional, can fail on some RPCs)
    usdt_before = get_token_balance(USDT, decimals=6)
    pol = get_pol_balance()
    print(f"Real USDT: {usdt_before:.2f} | POL: {pol:.2f}")

    if not should_run_cycle(state):
        return

    brain = BrainAgent(min_trade=3.0, max_trade=8.0, strat2_weight=0.75)
    decision = brain.decide_action(usdt_before, pol)

    swap_executed = False
    trade_size = 0.0
    
    if decision.startswith("TRADE_"):
        parts = decision.split("_")
        strat = parts[1]
        
        # Dynamic sizing: 25% of current USDT, capped between $10 and $25
        available_usdt = usdt_before  # Use actual USDT balance

	# === DYNAMIC TRADE SIZE (re-reads balance every cycle) ===
	usdt_balance = get_usdt_balance()  # fresh read every time
	trade_size = max(15.0, min(35.0, usdt_balance * 0.25))
	print(f"💰 Fresh USDT balance: ${usdt_balance:.2f} → Trade size: ${trade_size:.2f}")

        # Only trade if estimated net profit > $0.30 (after fees)
	estimated_net = (trade_size * 0.012) - fee_usd   # 1.2% expected gross

	if estimated_net < 0.30:
	    print(f"⏭️ Skipping - not profitable enough (est net ${estimated_net:.2f})")
	    return
        print(f"🚀 Brain decided: {strat} | Dynamic Size: ${size:.2f} (25% of ${available_usdt:.2f})")
        
	# === BIDIRECTIONAL LOGIC (make money both ways) ===
	weth_balance = get_weth_balance()
	weth_value_usd = weth_balance * 2350  # approx WETH price

	if weth_value_usd > 30:   # If we have >$30 in WETH, sell some back
	    direction = "WETH_TO_USDT"
	    amount_in = int(weth_balance * 0.3 * 1e18)   # sell 30% of WETH
	    print(f"🔄 Selling WETH back to USDT (we have ${weth_value_usd:.2f} in WETH)")
	else:
	    direction = "USDT_TO_WETH"
	    amount_in = int(trade_size * 1_000_000)
	    print(f"🔄 Buying WETH with USDT")

        # Execute swap with error handling
        tx_hash = await approve_and_swap(int(size * 1_000_000),direction=direction)
        if tx_hash:
            swap_executed = True
            print(f"✅ Swap executed successfully!")
            # Mark as profitable (we assume successful swaps are profitable)
            update_performance(was_profitable=True, fee_usd=0.8, trade_size=trade_size)
        else:
            print("⚠️ Swap failed")
            update_performance(was_profitable=False, fee_usd=0.5, trade_size=trade_size)
            state["last_run"] = time.time()
            save_state(state)
            print_performance()
            return
    
    # Print performance metrics
    print_performance()

    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
