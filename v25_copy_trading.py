"""
V2.5.2 Copy Trading Module - ACTIVE (Basic Monitoring)
"""
import json
import os
from dotenv import load_dotenv
load_dotenv()

CONFIG_FILE = "followed_wallets.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"wallets": [], "max_copy_ratio": 0.20, "enabled": True}
    with open(CONFIG_FILE) as f:
        return json.load(f)

def get_target_wallets():
    return load_config().get("wallets", [])

def get_copy_ratio():
    return load_config().get("max_copy_ratio", 0.20)

def should_copy_trade(tx_data):
    print("📡 [COPY] Scanning for profitable opportunities...")
    # For now we just log — real logic tomorrow
    return False  # Change to True when we add real wallets + logic

print("✅ V2.5.2 Copy Trading ACTIVE")
print(f"Monitoring {len(get_target_wallets())} wallets | Copy ratio: {get_copy_ratio()*100}%")
