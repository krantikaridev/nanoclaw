"""
V2.5.2 Copy Trading Module
- Loads wallets from followed_wallets.json
- Small size copy (configurable)
- Basic filters (will expand)
"""

import json
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_FILE = "followed_wallets.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"⚠️ {CONFIG_FILE} not found. Creating default...")
        default = {
            "wallets": ["0x...", "0x..."],
            "min_win_rate": 0.65,
            "max_copy_ratio": 0.08,
            "enabled": True
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(default, f, indent=2)
        return default
    with open(CONFIG_FILE) as f:
        return json.load(f)

def get_target_wallets():
    config = load_config()
    return config.get("wallets", [])

def get_copy_ratio():
    config = load_config()
    return config.get("max_copy_ratio", 0.08)

def should_copy_trade(tx_data):
    """Basic filter - expand later with real profit calculation"""
    profit_pct = tx_data.get("profit_pct", 0)
    return profit_pct >= load_config().get("min_win_rate", 0.65)

# === Status ===
config = load_config()
print("✅ V2.5.2 Copy Trading Module Loaded")
print(f"Monitoring {len(config.get('wallets', []))} wallets")
print(f"Copy ratio: {get_copy_ratio()*100}% | Min win rate: {config.get('min_win_rate')*100}%")
print("Ready for integration with main bot + protection layer")
