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
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 7))

w3 = Web3(Web3.HTTPProvider(RPC))
print(f"RPC connected: {w3.is_connected()}")

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
]

def get_pol_balance():
    return w3.eth.get_balance(WALLET) / 10**18

def get_token_balance(token_address: str, decimals: int = 6) -> float:
    if not token_address:
        return 0.0
    try:
        checksum_addr = Web3.to_checksum_address(token_address)
        contract = w3.eth.contract(address=checksum_addr, abi=ERC20_ABI)
        balance_wei = contract.functions.balanceOf(WALLET).call()
        return balance_wei / (10 ** decimals)
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

# === PERSISTENT PERFORMANCE TRACKER ===
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
        print("📊 No trades yet")
        return
    wins = sum(1 for t in trades if t.get("profitable", False))
    total = len(trades)
    win_rate = (wins / total) * 100 if total > 0 else 0
    total_fees = data.get("total_fees", 0.0)
    total_traded = sum(t.get("trade_size", 0) for t in trades)
    estimated_profit = (wins * 6.0) - total_fees
    print(f"┌─ 📊 PERFORMANCE (Last {total} trades)")
    print(f"├─ Win Rate: {win_rate:.1f}% ({wins}/{total})")
    print(f"├─ Total Traded: ${total_traded:.2f}")
    print(f"├─ Fees Paid: ${total_fees:.2f}")
    print(f"├─ Est. Gross PNL: ${estimated_profit:.2f}")
    print(f"└─ Remaining Capital: ${124.95 + estimated_profit:.2f}")

async def approve_and_swap(amount_in: int, direction="USDT_TO_WETH"):
    print(f"🚀 Executing REAL swap: {direction} | Amount: {amount_in}")

    try:
        if direction == "USDT_TO_WETH":
            token_in = USDT
            token_out = WETH
        else:
            token_in = WETH
            token_out = USDT

        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)
        router = Web3.to_checksum_address(ROUTER)

        erc20_abi = [
            {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
        ]

        # === APPROVE ===
        nonce = w3.eth.get_transaction_count(WALLET)
        approve_contract = w3.eth.contract(address=token_in, abi=erc20_abi)
        approve_tx = approve_contract.functions.approve(router, amount_in).build_transaction({
            "from": WALLET,
            "nonce": nonce,
            "gas": 140000,
            "gasPrice": w3.eth.gas_price * 15 // 10,
            "chainId": 137
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"✅ Approve Tx: {approve_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=300)
        if receipt["status"] == 0:
            print("❌ Approve failed!")
            return None
        print("✅ Approve confirmed!")
        await asyncio.sleep(5)

        # === SWAP with getAmountsOut ===
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
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"}
                ],
                "name": "getAmountsOut",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]

        swap_contract = w3.eth.contract(address=router, abi=router_abi)
        path = [token_in, token_out]

        amount_out_min = int(amount_in * 0.00042 * 0.97)   # Realistic for USDT → WETH (3% slippage)

        nonce_swap = w3.eth.get_transaction_count(WALLET)
        swap_tx = swap_contract.functions.swapExactTokensForTokens(
            amount_in,
            amount_out_min,
            path,
            WALLET,
            int(time.time()) + 300
        ).build_transaction({
            "from": WALLET,
            "nonce": nonce_swap,
            "gas": 300000,
            "gasPrice": w3.eth.gas_price * 15 // 10,
            "chainId": 137
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
        print(f"✅ REAL TX HASH: {swap_hash.hex()}")
        print(f"https://polygonscan.com/tx/{swap_hash.hex()}")

        receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=300)
        if receipt["status"] == 0:
            print("❌ Swap failed on-chain!")
            return None

        print("✅ Swap confirmed!")
        return swap_hash.hex()

    except Exception as e:
        print(f"❌ Error in approve_and_swap: {e}")
        import traceback
        traceback.print_exc()
        return None

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
        trade_size = max(15.0, min(35.0, usdt_balance * 0.25))
        print(f"💰 Fresh USDT: ${usdt_balance:.2f} → Trade size: ${trade_size:.2f}")

        try:
            weth_balance = get_token_balance(WETH, decimals=18)
            weth_value_usd = weth_balance * 2350
        except:
            weth_value_usd = 0

        if weth_value_usd > 50:
            direction = "WETH_TO_USDT"
            amount_in = int(weth_balance * 0.35 * 1e18)
            print(f"🔄 Selling WETH → USDT (${weth_value_usd:.2f} in WETH)")
        else:
            direction = "USDT_TO_WETH"
            amount_in = int(trade_size * 1_000_000)
            print(f"🔄 Buying WETH with USDT")

        fee_usd = 0.85
        estimated_net = (trade_size * 0.012) - fee_usd
        if estimated_net < -0.50:
            print(f"⏭️ Skipping - not profitable enough (est net ${estimated_net:.2f})")
            return

        tx_hash = await approve_and_swap(amount_in, direction=direction)
        if tx_hash:
            print("✅ Swap executed successfully!")
            update_performance(was_profitable=True, fee_usd=fee_usd, trade_size=trade_size)
        else:
            print("⚠️ Swap failed")
            update_performance(was_profitable=False, fee_usd=fee_usd, trade_size=trade_size)
            state["last_run"] = time.time()
            save_state(state)
            print_performance()
            return

    print_performance()
    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
