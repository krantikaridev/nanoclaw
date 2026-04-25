"""
V2.5.1 Protection Module
- Per-trade exit price locking
- Fluctuation protection (USDT low → auto sell)
- 5 obvious improvements (ready to integrate later)
"""

from web3 import Web3
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from constants import WALLET, USDT, WMATIC, ROUTER, ROUTER_ABI, GET_AMOUNTS_OUT_ABI

load_dotenv()

# ====================== CONFIG (Easy to change) ======================
MAX_DAILY_LOSS_PCT = 15          # Stop trading if daily loss > 15%
MIN_POL_BALANCE = 2.0            # Minimum POL to allow trades
MAX_TRADE_SIZE_USD = 35          # Never trade more than $35 in one go
GAS_MULTIPLIER = 1.25            # Dynamic gas (cheaper than 1.5x)
FLUCTUATION_USDT_THRESHOLD = 30  # If USDT < $30 → force sell 25% WMATIC
PROFIT_LOCK_PERCENT = 8          # Per-trade: sell when +8% from buy price

# ====================== HELPER FUNCTIONS ======================
def get_live_wmatic_price():
    w3 = Web3(Web3.HTTPProvider(os.getenv("RPC")))
    router = w3.eth.contract(address=ROUTER, abi=ROUTER_ABI + [GET_AMOUNTS_OUT_ABI])
    amounts = router.functions.getAmountsOut(10**18, [WMATIC, USDT]).call()
    return amounts[1] / 1_000_000

def get_balances():
    w3 = Web3(Web3.HTTPProvider(os.getenv("RPC")))
    usdt = w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]).functions.balanceOf(WALLET).call() / 1_000_000
    wmatic = w3.eth.contract(address=WMATIC, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]).functions.balanceOf(WALLET).call() / 1e18
    return usdt, wmatic

def get_pol_balance():
    w3 = Web3(Web3.HTTPProvider(os.getenv("RPC")))
    return w3.eth.get_balance(WALLET) / 10**18

# ====================== PER-TRADE EXIT PRICE LOCKING ======================
TRADE_LOG_FILE = "trade_exits.json"

def record_buy(buy_price, amount_usd, tx_hash):
    """Call this right after a successful USDT → WMATIC buy"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "buy_price": round(buy_price, 6),
        "target_price": round(buy_price * (1 + PROFIT_LOCK_PERCENT / 100), 6),
        "amount_usd": amount_usd,
        "tx_hash": tx_hash,
        "status": "OPEN"
    }
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE) as f: trades = json.load(f)
    else:
        trades = []
    trades.append(entry)
    with open(TRADE_LOG_FILE, "w") as f: json.dump(trades, f, indent=2)
    print(f"🔒 Trade locked | Buy: ${buy_price:.4f} | Target: ${entry['target_price']:.4f} (+{PROFIT_LOCK_PERCENT}%)")

def check_exit_conditions():
    """Call this before every cycle. Returns True if we should force sell"""
    usdt, wmatic = get_balances()
    
    # 1. Fluctuation protection (USDT too low)
    if usdt < FLUCTUATION_USDT_THRESHOLD and wmatic > 50:
        print(f"⚠️ FLUCTUATION PROTECTION: USDT ${usdt:.2f} < ${FLUCTUATION_USDT_THRESHOLD} → Selling 25% WMATIC")
        return True, "FLUCTUATION"
    
    # 2. Check open trades for per-trade exit
    if not os.path.exists(TRADE_LOG_FILE):
        return False, None
    
    with open(TRADE_LOG_FILE) as f:
        trades = json.load(f)
    
    current_price = get_live_wmatic_price()
    
    for t in trades:
        if t["status"] == "OPEN" and current_price >= t["target_price"]:
            print(f"🎯 PER-TRADE EXIT HIT | Buy ${t['buy_price']:.4f} → Current ${current_price:.4f} (+{PROFIT_LOCK_PERCENT}%)")
            return True, "PER_TRADE_EXIT"
    
    return False, None

# ====================== 5 OBVIOUS IMPROVEMENTS (Ready to use) ======================
def should_skip_due_to_daily_loss():
    # Placeholder - we can implement real daily P&L tracking later
    return False

def get_optimal_gas_price(w3):
    return int(w3.eth.gas_price * GAS_MULTIPLIER)

def has_enough_pol():
    return get_pol_balance() >= MIN_POL_BALANCE

def get_safe_trade_size(usdt_balance):
    return min(MAX_TRADE_SIZE_USD, usdt_balance * 0.28)

print("✅ V2.5.1 Protection Module loaded successfully")
