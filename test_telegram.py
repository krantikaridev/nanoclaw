import os
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")   # should now be numeric 5816538180

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("❌ Missing token or chat_id")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": f"[{datetime.now().strftime('%H:%M')}] NanoClaw:\n{message}",
        # No parse_mode for safety during testing
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        print("Response:", r.json())
        if r.json().get("ok"):
            print("✅ Telegram sent successfully")
            return True
        else:
            print("❌ Failed:", r.json())
            return False
    except Exception as e:
        print("❌ Error:", str(e))
        return False

send_telegram("Test from clean_swap bot. POL arrived (5.29). Rebalance attempted. USDT seed low. Portfolio ~$59.90.")
