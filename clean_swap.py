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

# === PERFORMANCE TRACKER ===
trade_history = []      # List of dicts: {profitable, fee, timestamp, trade_size}
total_fees_paid = 0.0
starting_usdt = 17.0    # Change this when you add more capital

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

def update_performance(was_profitable: bool, fee_usd: float = 0.8, trade_size: float = 0.0):
    """Record trade profitability and fees in persistent state"""
    global total_fees_paid
    
    trade_record = {
        "profitable": was_profitable,
        "fee": fee_usd,
        "trade_size": trade_size,
        "timestamp": time.time()
    }
    
    trade_history.append(trade_record)
    if len(trade_history) > 10:
        trade_history.pop(0)
    
    total_fees_paid += fee_usd
    
    status = "✅ PROFIT" if was_profitable else "❌ LOSS"
    print(f"📈 Trade Recorded: {status} | Size: ${trade_size:.2f} | Fee: ${fee_usd:.2f}")
    
    # Save to persistent state
    state = load_state()
    if "trades" not in state:
        state["trades"] = []
    state["trades"].append(trade_record)
    if len(state["trades"]) > 20:  # Keep last 20 trades
        state["trades"].pop(0)
    save_state(state)

def print_performance():
    """Display current performance metrics"""
    if not trade_history:
        print("📊 No trades yet - waiting for data...")
        return
    
    wins = sum(1 for t in trade_history if t["profitable"])
    total = len(trade_history)
    win_rate = (wins / total) * 100 if total > 0 else 0
    
    # Assume $6 profit per winning trade (average)
    estimated_profit_per_win = 6.0
    gross_pnl = (wins * estimated_profit_per_win) - total_fees_paid
    
    total_traded = sum(t["trade_size"] for t in trade_history)
    
    print(f"┌─ 📊 PERFORMANCE METRICS")
    print(f"├─ Win Rate: {win_rate:.1f}% ({wins}/{total})")
    print(f"├─ Total Traded: ${total_traded:.2f}")
    print(f"├─ Fees Paid: ${total_fees_paid:.2f}")
    print(f"├─ Est. Gross PNL: ${gross_pnl:.2f}")
    print(f"└─ Remaining Capital: ${starting_usdt + gross_pnl:.2f}")

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
            'gasPrice': w3.eth.gas_price * 13 // 10,
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
    
    # Read ACTUAL token balance BEFORE swap
    usdt_before = get_token_balance(USDT, decimals=6)
    weth_before = get_token_balance(WETH, decimals=18)
    pol = get_pol_balance()
    print(f"Real USDT: {usdt_before:.2f} | WETH: {weth_before:.6f} | POL: {pol:.2f}")

    if not should_run_cycle(state):
        return

    brain = BrainAgent(min_trade=3.0, max_trade=8.0, strat2_weight=0.75)
    decision = brain.decide_action(usdt_before, pol)

    swap_executed = False
    trade_size = 0.0
    
    if decision.startswith("TRADE_"):
        parts = decision.split("_")
        strat = parts[1]
        size = float(parts[2])
        trade_size = size
        print(f"🚀 Brain decided: {strat} ${size:.2f}")
        
        # Execute swap with error handling
        tx_hash = await approve_and_swap(int(size * 1_000_000))
        if tx_hash:
            swap_executed = True
            print(f"✅ Swap executed successfully!")
        else:
            print("⚠️ Swap failed")
            update_performance(was_profitable=False, fee_usd=0.5, trade_size=trade_size)
            state["last_run"] = time.time()
            save_state(state)
            print_performance()
            return
    
    # If swap executed, analyze profitability
    if swap_executed:
        await asyncio.sleep(3)  # Wait a bit for balance update
        
        # Read ACTUAL token balance AFTER swap
        usdt_after = get_token_balance(USDT, decimals=6)
        weth_after = get_token_balance(WETH, decimals=18)
        
        usdt_spent = usdt_before - usdt_after
        weth_gained = weth_after - weth_before
        
        # Assume breakeven WETH price is around $4.50 per WETH (adjust based on your data)
        breakeven_weth_price = 4.50
        
        # Check if we got a reasonable amount of WETH
        expected_weth = usdt_spent / breakeven_weth_price
        actual_slippage_pct = ((expected_weth - weth_gained) / expected_weth) * 100 if expected_weth > 0 else 0
        
        # Trade is profitable if slippage is low (< 2%)
        was_profitable = actual_slippage_pct < 2.0
        
        print(f"📊 Post-Swap Analysis:")
        print(f"   USDT Spent: ${usdt_spent:.2f}")
        print(f"   WETH Gained: {weth_gained:.6f}")
        print(f"   Slippage: {actual_slippage_pct:.2f}%")
        print(f"   Status: {'✅ Good!' if was_profitable else '⚠️ High slippage'}")
        
        # Record the trade
        update_performance(was_profitable=was_profitable, fee_usd=0.8, trade_size=trade_size)
    
    # Print performance metrics
    print_performance()

    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
