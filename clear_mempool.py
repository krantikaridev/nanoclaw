import os
from web3 import Web3
from dotenv import load_dotenv
import time
from datetime import datetime

load_dotenv()

WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = os.getenv("RPC", "https://polygon.drpc.org")

w3 = Web3(Web3.HTTPProvider(RPC))
print(f"[{datetime.now()}] RPC connected: {w3.is_connected()}")

def clear_mempool():
    print("🔧 Starting mempool clear sequence...")

    latest_nonce = w3.eth.get_transaction_count(WALLET, "latest")
    pending_nonce = w3.eth.get_transaction_count(WALLET, "pending")
    print(f"Current latest nonce: {latest_nonce} | Pending nonce: {pending_nonce}")

    # 0 POL self-transfer with high gas + EIP-155 chainId
    tx = {
        'from': WALLET,
        'to': WALLET,
        'value': 0,
        'gas': 21000,
        'gasPrice': w3.to_wei(300, 'gwei'),
        'nonce': latest_nonce,
        'chainId': 137,          # Polygon Mainnet
    }

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ Clear tx sent: {tx_hash.hex()}")
    print(f"https://polygonscan.com/tx/{tx_hash.hex()}")

    print("Waiting 45 seconds for network...")
    time.sleep(45)

    new_pending = w3.eth.get_transaction_count(WALLET, "pending") - w3.eth.get_transaction_count(WALLET, "latest")
    print(f"After clear attempt — pending txs: {new_pending}")

clear_mempool()
print("Mempool clear attempt completed. Now run clean_swap.py again.")
