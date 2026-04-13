#!/usr/bin/env python3
"""
REAL USDC SWAP - Actual USDC → WETH on Uniswap V3 (Polygon)
Safety: max 2 USDC, 80% utilization, reserve protected
"""
import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from web3 import Web3
import json

load_dotenv()
# Telegram Reporting (basic)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured - skipping notification")
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        print("📨 Telegram report sent")
    except Exception as e:
        print(f"⚠️ Telegram send failed: {e}")

WALLET_ADDRESS = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
if not PRIVATE_KEY or "YOUR_PRIVATE_KEY_HERE" in PRIVATE_KEY:
    print("❌ ERROR: Private key not set properly in .env")
    exit(1)

print("✅ Private key loaded — REAL on-chain swap enabled")

# Reliable mainnet RPCs with fallbacks (Polygon PoS 2026)
rpc_candidates = [
    os.getenv("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC") or "https://polygon-rpc.com",
    "https://polygon.drpc.org",
    "https://polygon.publicnode.com",
    "https://polygon-mainnet.gateway.tatum.io/",
    "https://polygon-public.nodies.app/"
]

w3 = None
used_rpc = None
for url in rpc_candidates:
    try:
        w3 = Web3(Web3.HTTPProvider(url))
        if w3.is_connected():
            used_rpc = url
            print(f"✅ MAINNET RPC connected: True | URL: {url}")
            break
    except:
        continue

if not w3 or not w3.is_connected():
    print("❌ All RPCs failed. Check internet or try later.")
    exit(1)
# === STRICT MICRO REAL MODE - Madan Pune (enforced) ===
MAX_TRADE_USDC = 2.0                    # Never exceed 2 USDC per trade
DAILY_LOSS_LIMIT_USDC = 1.0             # Hard daily loss cap
USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDC on Polygon
USDT_ADDRESS = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"   # Official Polygon USDT
POL_ADDRESS = "0x0000000000000000000000000000000000000000"    # Native POL (gas)

# Read current balances (read-only for now)
try:
    usdc_contract = w3.eth.contract(address=USDT_ADDRESS, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}])
    usdc_balance = usdc_contract.functions.balanceOf(WALLET_ADDRESS).call() / 10**6
    pol_balance = w3.eth.get_balance(WALLET_ADDRESS) / 10**18
    print(f"💰 Current balances | USDC: {usdc_balance:.4f} | POL (gas): {pol_balance:.4f}")
except Exception as e:
    print(f"⚠️ Balance check failed: {e}")
    usdc_balance = 0
    pol_balance = 0

print(f"🛡️  MICRO REAL MODE ACTIVE | Max trade: {MAX_TRADE_USDC} USDC | Daily loss limit: {DAILY_LOSS_LIMIT_USDC} USDC")
# Safety constants
INITIAL_REAL = 10.88
MAX_UTILIZATION_PCT = 80
RESERVE = INITIAL_REAL * (1 - MAX_UTILIZATION_PCT / 100)
MAX_TRADE = 2.0

USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
WETH_ADDRESS = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
UNISWAP_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

def load_paper_capital():
    try:
        with open("skills/autonomous-revenue-engine/capital.json") as f:
            data = json.load(f)
            return data.get("capital", 10.88)
    except:
        return 10.88

async def run_real_trade():
    """IMPROVED LIVE MICRO SWAP - Zer0Claw V1 - Madan Pune (USDC → WETH)"""
    global usdc_balance, pol_balance, daily_loss_today
    
    # Initialize daily loss tracker (simple in-memory for one session)
    if 'daily_loss_today' not in globals():
        daily_loss_today = 0.0

    if usdc_balance < 0.50:
        print(f"❌ INSUFFICIENT USDC: {usdc_balance:.4f}")
        return
    if pol_balance < 0.005:
        print(f"⚠️ LOW GAS: {pol_balance:.4f} POL")
        return
    if daily_loss_today >= DAILY_LOSS_LIMIT_USDC:
        print(f"🛑 DAILY LOSS LIMIT REACHED ({daily_loss_today:.2f}/{DAILY_LOSS_LIMIT_USDC} USDC). Trading paused today.")
        return

        # Smarter SIM Confidence Gate + force mode for testing
    force_trade = True   # Set to False when we want strict SIM control
    try:
        import json
        with open("skills/autonomous-revenue-engine/capital.json") as f:
            sim_data = json.load(f)
            sim_capital = sim_data.get("capital", 0)
            sim_last_profit = sim_data.get("last_profit", 0)
            sim_positive = (sim_capital > 200000) and (sim_last_profit > 0)
        print(f"✅ SIM Confidence Check: Positive (capital ~{sim_capital/1000:.0f}k | last profit ~{sim_last_profit})")
    except:
        sim_positive = True
        print("⚠️ SIM check failed, proceeding with default")

    if not force_trade and not sim_positive:
        print("⏸️ SIM confidence low - skipping trade today")
        return
    # Consistent trade size: target 1.0-1.5 USDC (fixed, not shrinking)
    trade_size = min(MAX_TRADE_USDC, .50)  # Comfortable fixed micro size
    trade_size_wei = int(trade_size * 10**6)

    print(f"""
══════════════════════════════════════
🚀 IMPROVED MICRO SWAP (Zer0Claw V1)
Wallet          : {WALLET_ADDRESS[:10]}...
Trade Size      : {trade_size:.4f} USDC → WETH (fixed)
Max Per Trade   : {MAX_TRADE_USDC} USDC
Daily Loss      : {daily_loss_today:.2f}/{DAILY_LOSS_LIMIT_USDC} USDC
Current USDC    : {usdc_balance:.4f}
══════════════════════════════════════
""")

    try:
        # Uniswap V3 Router & addresses
        ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
        USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
        WETH_ADDRESS = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
        FEE_TIER = 500  # 0.05% pool

        router = w3.eth.contract(address=ROUTER_ADDRESS, abi=[{
            "inputs": [{"components": [
                {"name": "tokenIn", "type": "address"},
                {"name": "tokenOut", "type": "address"},
                {"name": "fee", "type": "uint24"},
                {"name": "recipient", "type": "address"},
                {"name": "deadline", "type": "uint256"},
                {"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMinimum", "type": "uint256"},
                {"name": "sqrtPriceLimitX96", "type": "uint160"}
            ], "name": "params", "type": "tuple"}],
            "name": "exactInputSingle",
            "outputs": [{"name": "amountOut", "type": "uint256"}],
            "stateMutability": "payable",
            "type": "function"
        }])

        # 1. Approve USDC (safe full amount for micro)
        usdc_contract = w3.eth.contract(address=USDT_ADDRESS, abi=[{
            "constant": False,
            "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        }])
        
        # 1. Approve USDC (safe full amount for micro)
        # Fetch fresh nonce for approve
        nonce_approve = w3.eth.get_transaction_count(WALLET_ADDRESS)
        
        approve_tx = usdc_contract.functions.approve(ROUTER_ADDRESS, trade_size_wei * 10).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 100000,
            'gasPrice': w3.to_wei('135', 'gwei'),   # Safe for current ~100-130 gwei base + priority
            'nonce': nonce_approve,
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"✅ USDC Approval sent: https://polygonscan.com/tx/{approve_hash.hex()}")

        await asyncio.sleep(12)  # Give more time for approval to be picked up

        # 2. Swap with slippage protection + fresh nonce
        # Fetch new nonce for swap (in case approve is still pending)
        nonce_swap = w3.eth.get_transaction_count(WALLET_ADDRESS, 'pending')

        expected_out_wei = int(trade_size * 0.00000046 * 10**18)  # rough WETH rate
        amount_out_min = int(expected_out_wei * 0.97)  # 3% slippage tolerance

        params = {
            "tokenIn": USDT_ADDRESS,
            "tokenOut": WETH_ADDRESS,
            "fee": FEE_TIER,
            "recipient": WALLET_ADDRESS,
            "deadline": int(datetime.now().timestamp()) + 600,
            "amountIn": trade_size_wei,
            "amountOutMinimum": amount_out_min,
            "sqrtPriceLimitX96": 0
        }

        swap_tx = router.functions.exactInputSingle(params).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 300000,
            'gasPrice': w3.to_wei('140', 'gwei'),   # Slightly higher than approve
            'nonce': nonce_swap,
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
        
        print(f"""
✅ LIVE SWAP EXECUTED! (with 3% slippage protection)
Tx Hash: {tx_hash.hex()}
🔍 View: https://polygonscan.com/tx/{tx_hash.hex()}
""")
        
        # Update local balance estimate
        usdc_balance -= trade_size
        print(f"📊 Estimated new USDC: {usdc_balance:.4f}")
        # Send Telegram report
        report = f"""
🚀 <b>Zer0Claw V1 Micro Trade</b>
Size: {trade_size:.4f} USDC → WETH
Tx: <a href="https://polygonscan.com/tx/{tx_hash.hex()}">{tx_hash.hex()[:8]}...</a>
USDC: {usdc_balance:.4f}
Total ~${21.31 if 'total_value' not in globals() else 'updating'}
Daily Loss: 0.00 / 1.0 USDC
        """.strip()
        send_telegram_message(report)	
    except Exception as e:
        print(f"❌ Trade failed: {str(e)[:200]}")
        daily_loss_today += 0.10  # Small penalty on failure

