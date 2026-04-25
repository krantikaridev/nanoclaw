import json
import os
from datetime import datetime

LOG_FILE = "trade_history.json"

def log_trade(direction, amount_usd, tx_hash, success=True, note=""):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "direction": direction,
        "amount_usd": round(amount_usd, 2),
        "tx_hash": tx_hash,
        "success": success,
        "note": note
    }
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            history = json.load(f)
    else:
        history = []
    history.append(entry)
    with open(LOG_FILE, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"📝 Trade logged: {direction} ${amount_usd:.2f}")
