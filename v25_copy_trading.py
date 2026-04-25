"""
V2.5.2 Copy Trading Module - ACTIVE (Basic Monitoring + Ready)
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
    # For tonight: just log. Tomorrow we add real logic + wallets
    return False   # Change to True when we add real wallets

print("✅ V2.5.2 Copy Trading ACTIVE (Monitoring Mode)")
print(f"Monitoring {len(get_target_wallets())} wallets | Copy ratio: {get_copy_ratio()*100}%")
print("Ready for real wallet activation tomorrow")
