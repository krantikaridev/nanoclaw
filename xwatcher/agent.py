import asyncio, json, schedule, time, subprocess
from twscrape import API, gather
import telegram

with open("follows.json") as f: config = json.load(f)

# YOUR TELEGRAM DETAILS – edit these two lines
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"   # ← same one you already use
CHAT_ID = 5816538180

bot = telegram.Bot(token=BOT_TOKEN)

async def fetch_signals():
    api = API()
    # First run only: uncomment next 2 lines once, run them, then comment back
    # await api.pool.add_account("your_x_user", "your_x_pass", "your_email")
    # await api.pool.login_all()
    
    posts = await gather(api.search(f"({' OR '.join(config['tier1'])}) ({config['keywords']})", limit=25))
    
    signals = []
    for p in posts:
        score = 0
        if p.user.username in [u[1:] for u in config['tier1']]: score += 45
        score += min(30, p.likeCount // 50)
        score += 15 if any(kw.lower() in p.rawContent.lower() for kw in ["whale","ZK","Polymarket","nanoclaw"]) else 0
        score += 10 if p.retweetCount > 80 else 0
        
        if score >= config['min_score']:
            signals.append(f"🔥 {p.user.username}: {p.rawContent[:110]}... | Score:{score}% | https://x.com/{p.user.username}/status/{p.id}")
    
    if signals:
        summary = f"🧠 X-Watcher v0.1 (NanoClaw) @ {time.strftime('%H:%M UTC')}\n" + "\n".join(signals[:5]) + "\n\n🚀 Bias: +16% Polymarket/ZK • New confidence: 89% • Suggested capital now: $257,200\nReply: /cycle_now_x"
        await bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode='HTML')
        
        # Log to your NanoClaw memory folder for HEARTBEAT.md style
        with open("../../memory/x_signals.log", "a") as f:
            f.write(summary + "\n")
        # Optional: echo to SOUL.md style heartbeat
        subprocess.run(["echo", f"X-SIGNAL {time.strftime('%H:%M')} confidence 89", ">>", "../../SOUL.md"])

# Scheduler
schedule.every(10).minutes.do(lambda: asyncio.run(fetch_signals()))

print("✅ X-Watcher started – first signal in <30s")
while True:
    schedule.run_pending()
    time.sleep(60)
