"""
V2.5.2 Copy Trading Module
- Monitor authentic Polygon wallets
- Copy profitable trades (any pair)
- Small size (5-10% of their trade)
- Win rate + consistency filter
"""

import json
import time
from web3 import Web3
from dotenv import load_dotenv
import os

load_dotenv()

# === CONFIG ===
TARGET_WALLETS = [
    # Add 3-5 real wallets here (from your X research)
    "0x...",  
    "0x...",
]

COPY_RATIO = 0.08          # 8% of their trade size (safe start)
MIN_PROFIT_PCT = 1.5       # Only copy if they made at least +1.5%

def load_followed_wallets():
    return TARGET_WALLETS

def should_copy_trade(tx_data):
    """Basic filter - will be expanded"""
    if tx_data.get("profit_pct", 0) < MIN_PROFIT_PCT:
        return False
    return True

print("✅ V2.5.2 Copy Trading Module loaded")
print(f"Monitoring {len(TARGET_WALLETS)} wallets | Copy ratio: {COPY_RATIO*100}%")
print("Ready for integration with main bot + protection layer")
