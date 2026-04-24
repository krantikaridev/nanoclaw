from brain_agent import BrainAgent
import os
import time
import sys
import asyncio
import json
import subprocess
from datetime import datetime
from web3 import Web3
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════════════════
# VERSION CONTROL - Feature Flag System (V2.5 vs V2.2)
# ═══════════════════════════════════════════════════════════════════════════
USE_V25 = os.getenv("USE_V25", "false").lower() == "true"
VERSION = "V2.5" if USE_V25 else "V2.2"

print(f"\n{'='*70}")
print(f"  🤖 NANOCLAW {VERSION} - {datetime.now().isoformat()}")
print(f"{'='*70}\n")

# ═══════════════════════════════════════════════════════════════════════════
# CRON SELF-HEALING SYSTEM - Embedded cron management
# ═══════════════════════════════════════════════════════════════════════════

def ensure_cron_exists():
    """
    Verify cron job exists. If not, recreate it.
    This handles git stash/pull/pop cycles that delete crontab.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, "clean_swap.py")
    
    # Determine cron schedule based on version
    if USE_V25:
        cron_schedule = "*/5 * * * *"   # V2.5: every 5 minutes
        cron_desc = "every 5 minutes (V2.5)"
    else:
        cron_schedule = "*/10 * * * *"  # V2.2: every 10 minutes
        cron_desc = "every 10 minutes (V2.2)"
    
    # Cron command with Python full path
    python_path = sys.executable
    cron_cmd = f"{cron_schedule} cd {script_dir} && {python_path} clean_swap.py >> bot.log 2>&1"
    
    try:
        # Check if cron job already exists
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5
        )
        existing_crons = result.stdout
        
        # Check if our job exists
        if "clean_swap.py" in existing_crons:
            # Cron exists, check if it's up to date
            if cron_desc in existing_crons or cron_schedule in existing_crons:
                print(f"✅ Cron job verified: {cron_desc}")
                return True
            else:
                print(f"⚠️ Cron job exists but may be outdated, skipping update")
                return True
        else:
            # Cron missing - recreate it
            print(f"⚠️ Cron job missing! Recreating...")
            all_crons = existing_crons if existing_crons.strip() else ""
            
            # Add our cron job
            new_cron = all_crons.rstrip() + "\n" + cron_cmd + "\n"
            
            # Install updated crontab
            process = subprocess.Popen(
                ["crontab", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=new_cron, timeout=5)
            
            if process.returncode == 0:
                print(f"✅ Cron job restored: {cron_desc}")
                return True
            else:
                print(f"❌ Failed to restore cron: {stderr}")
                return False
    
    except subprocess.TimeoutExpired:
        print("⚠️ Cron check timeout - skipping")
        return True
    except FileNotFoundError:
        print("⚠️ crontab not available on this system")
        return True
    except Exception as e:
        print(f"⚠️ Cron check error: {e}")
        return True

# ═══════════════════════════════════════════════════════════════════════════
# LOCK MECHANISM - Prevents concurrent runs
# ═══════════════════════════════════════════════════════════════════════════
LOCK_FILE = "/tmp/nanoclaw.lock"

# Set cooldown based on version
if USE_V25:
    COOLDOWN_SECONDS = 5 * 60      # V2.5: 5 minutes
    COOLDOWN_MINUTES = 5
else:
    COOLDOWN_SECONDS = 10 * 60     # V2.2: 10 minutes (unchanged)
    COOLDOWN_MINUTES = 10

if os.path.exists(LOCK_FILE) and (time.time() - os.path.getmtime(LOCK_FILE) < COOLDOWN_SECONDS):
    print("⛔ Lock active — skipping")
    sys.exit(0)
open(LOCK_FILE, 'w').close()

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════
# WALLET & RPC CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = os.getenv("RPC", "https://polygon.drpc.org")

USDT = os.getenv("USDT")
WETH = os.getenv("WETH")
ROUTER = os.getenv("ROUTER")

w3 = Web3(Web3.HTTPProvider(RPC))
print(f"RPC connected: {w3.is_connected()}")

# ═══════════════════════════════════════════════════════════════════════════
# VERSION-SPECIFIC STATE FILE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════
if USE_V25:
    STATE_FILE = "bot_state_v25.json"
    PERF_FILE = "bot_performance_v25.json"
else:
    STATE_FILE = "bot_state.json"
    PERF_FILE = None  # V2.2 doesn't use separate perf file

# ═══════════════════════════════════════════════════════════════════════════
# V2.5 SPECIFIC CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
if USE_V25:
    # V2.5 Trade Parameters
    MIN_TRADE_USDT = 15.0          # Minimum trade size (V2.5)
    MAX_TRADE_USDT = 35.0          # Maximum trade size (V2.5)
    TRADE_SIZE_PCT = 0.25          # 25% of current USDT balance
    
    # V2.5 Risk Management
    STARTING_CAPITAL_USDT = 100.0  # Reference capital for daily loss calculation
    MAX_DAILY_LOSS_PCT = 0.08      # 8% of starting capital
    MAX_DAILY_LOSS_USD = STARTING_CAPITAL_USDT * MAX_DAILY_LOSS_PCT
    
    # V2.5 Gas Pricing
    GAS_PRICE_BUMP_PCT = 0.15      # +15% (smart) instead of +30% (fixed)
    
    # V2.5 Rebalancing
    WETH_REBALANCE_THRESHOLD = 0.15  # If WETH > 15% of portfolio
    
    print(f"📊 V2.5 Configuration:")
    print(f"  ├─ Trade Size: ${MIN_TRADE_USDT}-${MAX_TRADE_USDT} (25% of USDT)")
    print(f"  ├─ Max Daily Loss: ${MAX_DAILY_LOSS_USD:.2f} (8% safeguard)")
    print(f"  ├─ Gas Bump: +{GAS_PRICE_BUMP_PCT*100:.0f}% (smart pricing)")
    print(f"  ├─ Rebalance: >{WETH_REBALANCE_THRESHOLD*100:.0f}% WETH → USDT")
    print(f"  └─ Cooldown: {COOLDOWN_MINUTES} min\n")

else:
    # V2.2 Legacy Configuration
    print(f"📊 V2.2 Configuration (Legacy Mode):")
    print(f"  ├─ Trade Size: $10-$25 dynamic (unchanged)")
    print(f"  ├─ Gas Bump: +30% (unchanged)")
    print(f"  └─ Cooldown: {COOLDOWN_MINUTES} min\n")

# ═══════════════════════════════════════════════════════════════════════════
# ERC20 ABI for balance and approve
# ═══════════════════════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════════════════════
# V2.2 LEGACY - In-memory performance tracking (unchanged)
# ═══════════════════════════════════════════════════════════════════════════
if not USE_V25:
    trade_history = []      # List of dicts: {profitable, fee, timestamp, trade_size}
    total_fees_paid = 0.0
    starting_usdt = 17.0    # V2.2 fallback value

# ═══════════════════════════════════════════════════════════════════════════
# BALANCE & STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def get_pol_balance():
    """Get POL (native coin) balance"""
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

def get_portfolio_value(usdt_bal: float, weth_bal: float, weth_price_usd: float = 3000.0) -> tuple:
    """
    Calculate total portfolio value and allocation percentages.
    Returns: (total_value, usdt_pct, weth_pct)
    V2.5 only.
    """
    if not USE_V25:
        return 0.0, 0.0, 0.0
    
    usdt_value = usdt_bal
    weth_value = weth_bal * weth_price_usd
    total = usdt_value + weth_value
    
    if total == 0:
        return 0.0, 0.0, 0.0
    
    usdt_pct = (usdt_value / total) * 100
    weth_pct = (weth_value / total) * 100
    
    return total, usdt_pct, weth_pct

def load_state():
    """Load persistent bot state"""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        if USE_V25:
            return {"last_run": 0, "cycle_count": 0}
        else:
            return {"last_run": 0, "trades": []}

def save_state(state):
    """Save persistent bot state"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def should_run_cycle(state):
    """Check if enough time has passed since last cycle"""
    now = time.time()
    if now - state.get("last_run", 0) < COOLDOWN_SECONDS:
        remaining = COOLDOWN_SECONDS - (now - state.get("last_run", 0))
        print(f"⏳ Cooldown active ({remaining:.0f}s remaining) — skipping")
        return False
    if get_pol_balance() < 2.0:
        print("⚠️ POL low — skipping")
        return False
    return True

# ═══════════════════════════════════════════════════════════════════════════
# V2.5 SPECIFIC - PERFORMANCE TRACKING & DAILY SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

def load_performance_v25() -> dict:
    """Load persistent performance metrics (V2.5 only)"""
    try:
        with open(PERF_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "trades": [],
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "daily_trades": 0,
            "daily_loss": 0.0,
            "last_daily_reset": datetime.utcnow().date().isoformat(),
            "starting_capital": STARTING_CAPITAL_USDT,
            "all_time_wins": 0,
            "all_time_total": 0,
            "paused_until": None
        }

def save_performance_v25(perf: dict):
    """Save persistent performance metrics (V2.5 only)"""
    with open(PERF_FILE, 'w') as f:
        json.dump(perf, f, indent=2)

def check_daily_reset_v25(perf: dict) -> dict:
    """Check if we need to reset daily metrics and print daily summary (V2.5 only)"""
    today = datetime.utcnow().date().isoformat()
    last_reset = perf.get("last_daily_reset", today)
    
    if today != last_reset:
        # Print yesterday's summary before reset
        print_daily_summary_v25(perf, last_reset)
        
        # Reset daily metrics for today
        perf["daily_trades"] = 0
        perf["daily_loss"] = 0.0
        perf["last_daily_reset"] = today
        perf["paused_until"] = None
        save_performance_v25(perf)
    
    return perf

def print_daily_summary_v25(perf: dict, date_str: str):
    """Print a clean daily report (V2.5 only)"""
    daily_trades = perf.get("daily_trades", 0)
    
    if daily_trades == 0:
        return  # No trades yesterday
    
    # Calculate metrics
    all_trades = perf.get("trades", [])
    total_fees = perf.get("total_fees", 0.0)
    total_pnl = perf.get("total_pnl", 0.0)
    starting_cap = perf.get("starting_capital", STARTING_CAPITAL_USDT)
    current_cap = starting_cap + total_pnl
    
    all_time_wins = perf.get("all_time_wins", 0)
    all_time_total = perf.get("all_time_total", 0)
    all_time_win_rate = (all_time_wins / all_time_total * 100) if all_time_total > 0 else 0
    
    daily_loss = perf.get("daily_loss", 0.0)
    
    print(f"""
╔════════════════════════════════════════════════════════════════════╗
║                  📊 DAILY SUMMARY - {date_str}                      ║
╠════════════════════════════════════════════════════════════════════╣
║ Trades Yesterday      : {daily_trades:>3}                                    ║
║ Daily Loss            : ${daily_loss:>8.2f} / ${MAX_DAILY_LOSS_USD:>8.2f}                  ║
║                        |                                           ║
║ All-Time Metrics:                                                  ║
║  ├─ Win Rate          : {all_time_win_rate:>6.1f}% ({all_time_wins}/{all_time_total})                       ║
║  ├─ Total Fees        : ${total_fees:>8.2f}                             ║
║  ├─ Net PNL           : ${total_pnl:>+8.2f}                            ║
║  ├─ Starting Capital  : ${starting_cap:>8.2f}                             ║
║  └─ Current Capital   : ${current_cap:>8.2f}                             ║
╚════════════════════════════════════════════════════════════════════╝
""")

def update_performance_v25(perf: dict, was_profitable: bool, fee_usd: float, pnl_usd: float, trade_size: float):
    """Record trade metrics persistently for V2.5"""
    trade_record = {
        "timestamp": datetime.utcnow().isoformat(),
        "profitable": was_profitable,
        "fee": fee_usd,
        "pnl": pnl_usd,
        "trade_size": trade_size
    }
    
    perf["trades"].append(trade_record)
    if len(perf["trades"]) > 1000:  # Keep last 1000 trades
        perf["trades"].pop(0)
    
    perf["total_fees"] += fee_usd
    perf["total_pnl"] += pnl_usd
    perf["daily_trades"] = perf.get("daily_trades", 0) + 1
    
    # Track all-time win rate
    perf["all_time_total"] = perf.get("all_time_total", 0) + 1
    if was_profitable:
        perf["all_time_wins"] = perf.get("all_time_wins", 0) + 1
    
    if pnl_usd < 0:
        perf["daily_loss"] += abs(pnl_usd)
    
    save_performance_v25(perf)
    
    status = "✅" if was_profitable else "❌"
    print(f"{status} Trade recorded | PNL: ${pnl_usd:+.2f} | Fee: ${fee_usd:.2f}")

# ═══════════════════════════════════════════════════════════════════════════
# V2.2 LEGACY - PERFORMANCE TRACKING (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

def update_performance_v22(was_profitable: bool, fee_usd: float = 0.8, trade_size: float = 0.0):
    """Record trade profitability and fees in persistent state (V2.2 unchanged)"""
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

def print_performance_v22():
    """Display current performance metrics (V2.2 unchanged)"""
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

# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY REGISTRY - Extensible for future strategies
# ═══════════════════════════════════════════════════════════════════════════

STRATEGIES = {
    "baseline": {
        "name": "Baseline USDT→WETH Swap",
        "description": "Simple swap with BrainAgent decision logic",
        "enabled": True,
        "min_size": MIN_TRADE_USDT if USE_V25 else 10.0,
    },
    # TODO: Add X Signal Strategy here
    # "x_signal": {
    #     "name": "X Signal Strategy",
    #     "description": "Monitor X (Twitter) signals for trading opportunities",
    #     "enabled": False,
    #     "min_size": MIN_TRADE_USDT if USE_V25 else 10.0,
    # },
    # TODO: Add Expert Account Strategy here
    # "expert_account": {
    #     "name": "Expert Account Replication",
    #     "description": "Copy trades from expert traders / copy trading",
    #     "enabled": False,
    #     "min_size": MIN_TRADE_USDT if USE_V25 else 10.0,
    # },
}

def select_strategy():
    """Select an enabled strategy for this cycle"""
    enabled = [k for k, v in STRATEGIES.items() if v["enabled"]]
    if not enabled:
        return None
    return enabled[0]  # Simple: return first enabled, can randomize later

# ═══════════════════════════════════════════════════════════════════════════
# GAS PRICING - Version-specific
# ═══════════════════════════════════════════════════════════════════════════

def calculate_gas_price():
    """
    Calculate optimized gas price based on version:
    - V2.5: current gas + 15% bump (smart)
    - V2.2: current gas + 30% bump (fixed, unchanged)
    """
    base_price = w3.eth.gas_price
    
    if USE_V25:
        bumped_price = int(base_price * (1 + GAS_PRICE_BUMP_PCT))
    else:
        bumped_price = int(base_price * 13 // 10)  # +30% (V2.2 legacy)
    
    return bumped_price

# ═══════════════════════════════════════════════════════════════════════════
# V2.5 SPECIFIC - AUTO-REBALANCING
# ═══════════════════════════════════════════════════════════════════════════

async def check_and_rebalance_v25(perf: dict, usdt_bal: float, weth_bal: float, weth_price: float = 3000.0) -> bool:
    """
    If WETH > 15% of portfolio value, convert excess back to USDT (V2.5 only)
    """
    if not USE_V25:
        return False
    
    total_val, usdt_pct, weth_pct = get_portfolio_value(usdt_bal, weth_bal, weth_price)
    
    if weth_pct > WETH_REBALANCE_THRESHOLD * 100:
        # Calculate excess WETH
        target_weth_value = total_val * WETH_REBALANCE_THRESHOLD
        excess_weth_value = (weth_pct / 100 * total_val) - target_weth_value
        excess_weth = excess_weth_value / weth_price
        
        print(f"""
🔄 AUTO-REBALANCE TRIGGERED
├─ Current WETH: {weth_pct:.1f}% (threshold: {WETH_REBALANCE_THRESHOLD*100:.0f}%)
├─ Excess WETH: {excess_weth:.6f} WETH (${excess_weth_value:.2f})
└─ Converting WETH → USDT...
""")
        
        # Execute WETH → USDT swap
        tx_hash = await approve_and_swap(int(excess_weth * 10**18), direction="WETH_TO_USDT")
        if tx_hash:
            print(f"✅ Rebalance completed: {tx_hash}")
            
            # Record rebalance as a trade with 0 PNL (net neutral)
            update_performance_v25(perf, was_profitable=True, fee_usd=1.0, pnl_usd=0.0, trade_size=excess_weth_value)
            return True
        else:
            print("⚠️ Rebalance failed")
            return False
    
    return False

# ═══════════════════════════════════════════════════════════════════════════
# SWAP EXECUTION - Core trading logic with version-specific enhancements
# ═══════════════════════════════════════════════════════════════════════════

async def approve_and_swap(amount_in: int, direction="USDT_TO_WETH"):
    """
    Execute approve + swap transactions with version-specific logic:
    - V2.5: Smart gas pricing (15% bump), force balance re-reads
    - V2.2: Fixed gas pricing (30% bump), standard flow (unchanged)
    """
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
        gas_price = calculate_gas_price()

        # === APPROVE ===
        approve_contract = w3.eth.contract(address=token_in, abi=erc20_abi)
        approve_tx = approve_contract.functions.approve(router, amount_in).build_transaction({
            'from': WALLET,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': gas_price,
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
        router_abi = QUICKSWAP_ROUTER_ABI
        swap_contract = w3.eth.contract(address=router, abi=router_abi)
        path = [token_in, token_out]
        
        nonce_swap = w3.eth.get_transaction_count(WALLET)
        swap_tx = swap_contract.functions.swapExactTokensForTokens(
            amount_in, 0, path, WALLET, int(time.time()) + 300
        ).build_transaction({
            'from': WALLET,
            'nonce': nonce_swap,
            'gas': 200000,
            'gasPrice': gas_price,
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

        # === FORCE BALANCE RE-READ (V2.5 ONLY) ===
        if USE_V25:
            print("🔄 Force re-reading on-chain balances...")
            await asyncio.sleep(3)
            usdt_after = get_token_balance(USDT, decimals=6)
            weth_after = get_token_balance(WETH, decimals=18)
            print(f"📊 Updated Balances: USDT={usdt_after:.2f} | WETH={weth_after:.6f}")
        
        # Return the transaction hash for future tracking
        return swap_hash.hex()
        
    except Exception as e:
        print(f"❌ Error in approve_and_swap: {e}")
        import traceback
        traceback.print_exc()
        return None

# ═══════════════════════════════════════════════════════════════════════════
# MAIN BOT LOGIC - Version-aware orchestration
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    """Main bot cycle - orchestrates V2.5 or V2.2 logic"""
    
    # ═══════════════════════════════════════════════════════════════════════
    # CRON SELF-HEALING CHECK (runs on every cycle)
    # ═══════════════════════════════════════════════════════════════════════
    ensure_cron_exists()
    
    state = load_state()
    
    # ═══════════════════════════════════════════════════════════════════════
    # V2.5 INITIALIZATION
    # ═══════════════════════════════════════════════════════════════════════
    perf = None
    if USE_V25:
        perf = load_performance_v25()
        
        # Check if it's a new day and print daily summary
        perf = check_daily_reset_v25(perf)
        
        # Check if trading is paused due to daily loss limit
        paused_until = perf.get("paused_until")
        if paused_until and datetime.utcnow().isoformat() < paused_until:
            print(f"""
🛑 DAILY LOSS LIMIT REACHED
├─ Daily Loss: ${perf['daily_loss']:.2f} / ${MAX_DAILY_LOSS_USD:.2f}
└─ Trading paused until tomorrow (UTC)
""")
            state["last_run"] = time.time()
            save_state(state)
            return

    # ═══════════════════════════════════════════════════════════════════════
    # READ CURRENT BALANCES
    # ═══════════════════════════════════════════════════════════════════════
    usdt_before = get_token_balance(USDT, decimals=6)
    weth_before = get_token_balance(WETH, decimals=18)
    pol = get_pol_balance()
    print(f"Real USDT: {usdt_before:.2f} | WETH: {weth_before:.6f} | POL: {pol:.2f}")

    if not should_run_cycle(state):
        return

    # ═══════════════════════════════════════════════════════════════════════
    # V2.5 AUTO-REBALANCING
    # ═══════════════════════════════════════════════════════════════════════
    if USE_V25:
        rebalanced = await check_and_rebalance_v25(perf, usdt_before, weth_before)
        if rebalanced:
            # Re-read balances after rebalance
            usdt_before = get_token_balance(USDT, decimals=6)
            weth_before = get_token_balance(WETH, decimals=18)
            print(f"Post-Rebalance: USDT={usdt_before:.2f} | WETH={weth_before:.6f}")

    # ═══════════════════════════════════════════════════════════════════════
    # STRATEGY SELECTION & BRAIN AGENT DECISION
    # ═══════════════════════════════════════════════════════════════════════
    strategy = select_strategy()
    if not strategy:
        print("⚠️ No strategies enabled - skipping")
        state["last_run"] = time.time()
        save_state(state)
        return

    # Configure BrainAgent based on version
    if USE_V25:
        brain = BrainAgent(
            min_trade=MIN_TRADE_USDT,
            max_trade=MAX_TRADE_USDT,
            strat2_weight=0.75
        )
    else:
        brain = BrainAgent(min_trade=3.0, max_trade=8.0, strat2_weight=0.75)
    
    decision = brain.decide_action(usdt_before, pol)

    # ═══════════════════════════════════════════════════════════════════════
    # TRADE EXECUTION
    # ═══════════════════════════════════════════════════════════════════════
    swap_executed = False
    trade_size = 0.0
    
    if decision.startswith("TRADE_"):
        parts = decision.split("_")
        strat = parts[1]
        
        # Calculate trade size based on version
        if USE_V25:
            # V2.5: 25% of current USDT, bounded by $15-$35
            size = max(MIN_TRADE_USDT, min(MAX_TRADE_USDT, usdt_before * TRADE_SIZE_PCT))
        else:
            # V2.2: 25% of current USDT, bounded by $10-$25 (unchanged)
            size = max(10.0, min(25.0, usdt_before * 0.25))
        
        trade_size = size
        print(f"🚀 Brain decided: {strat} | Dynamic Size: ${size:.2f}")
        
        # Execute USDT → WETH swap
        tx_hash = await approve_and_swap(int(size * 1_000_000), direction="USDT_TO_WETH")
        
        if tx_hash:
            swap_executed = True
            
            # Calculate mock PNL (assume 0.5% average profit per trade)
            pnl = size * 0.005
            fee = 0.8
            
            if USE_V25:
                update_performance_v25(perf, was_profitable=True, fee_usd=fee, pnl_usd=pnl, trade_size=trade_size)
                
                # Check if daily loss limit exceeded after this trade
                if perf["daily_loss"] >= MAX_DAILY_LOSS_USD:
                    tomorrow = (datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) 
                               + __import__('datetime').timedelta(days=1)).isoformat()
                    perf["paused_until"] = tomorrow
                    save_performance_v25(perf)
                    print(f"\n⚠️ Daily loss limit reached (${perf['daily_loss']:.2f}/${MAX_DAILY_LOSS_USD:.2f})")
                    print(f"   Trading paused until tomorrow UTC")
            else:
                update_performance_v22(was_profitable=True, fee_usd=fee, trade_size=trade_size)
            
            print(f"✅ Swap executed successfully!")
        else:
            if USE_V25:
                update_performance_v25(perf, was_profitable=False, fee_usd=0.5, pnl_usd=-0.5, trade_size=trade_size)
            else:
                update_performance_v22(was_profitable=False, fee_usd=0.5, trade_size=trade_size)
            
            print("⚠️ Swap failed")
            state["last_run"] = time.time()
            save_state(state)
            if USE_V25:
                pass  # V2.5 already printed detailed metrics
            else:
                print_performance_v22()
            return

    # ═══════════════════════════════════════════════════════════════════════
    # PERFORMANCE REPORTING
    # ═══════════════════════════════════════════════════════════════════════
    if USE_V25:
        # V2.5 Enhanced metrics
        wins = perf.get("all_time_wins", 0)
        total = perf.get("all_time_total", 0)
        win_rate = (wins / total * 100) if total > 0 else 0
        
        print(f"""
📈 PERFORMANCE (V2.5)
├─ All-Time Win Rate: {win_rate:.1f}% ({wins}/{total})
├─ Net PNL: ${perf['total_pnl']:+.2f}
├─ Total Fees: ${perf['total_fees']:.2f}
├─ Daily Loss: ${perf['daily_loss']:.2f} / ${MAX_DAILY_LOSS_USD:.2f}
└─ Cycles: {state.get('cycle_count', 0)}
""")
    else:
        # V2.2 Legacy metrics
        print_performance_v22()

    # ═══════════════════════════════════════════════════════════════════════
    # UPDATE STATE & EXIT
    # ═══════════════════════════════════════════════════════════════════════
    state["last_run"] = time.time()
    state["cycle_count"] = state.get("cycle_count", 0) + 1
    save_state(state)
    
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
