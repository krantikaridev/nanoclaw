"""
V2.5.2 Copy Trading Module - ACTIVE
"""

import json
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_FILE = "followed_wallets.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"⚠️ {CONFIG_FILE} not found.")
        return {"wallets": [], "max_copy_ratio": 0.20, "enabled": True}
    with open(CONFIG_FILE) as f:
        return json.load(f)

def get_target_wallets():
    return load_config().get("wallets", [])

def get_copy_ratio():
    return load_config().get("max_copy_ratio", 0.20)

def should_copy_trade(tx_data):
    # Placeholder - will expand with real logic tomorrow
    return True

print("✅ V2.5.2 Copy Trading Module ACTIVE")
print(f"Monitoring {len(get_target_wallets())} wallets | Copy ratio: {get_copy_ratio()*100}%")
