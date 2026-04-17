# config_real.py - Real money config for v2 (Madan Pune)
# All parameters here are changeable without touching strategy code

TRADE_SIZE_USDT = 2.0                    # Your requested size - 2 USDT per trade to beat fees
MAX_DAILY_LOSS_USDT = 10.0               # Testing allowance
MIN_EDGE_PCT = 3.0                       # Only trade if edge is at least 3%
SIM_CONFIDENCE_THRESHOLD = 200000        # SIM capital above this = strong signal
ACTIVE_STRATEGIES = ["baseline", "polymarket"]

# Wallet & RPC
WALLET_ADDRESS = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
RPC_URL = "https://polygon.drpc.org"

# Daily alternation to run only 2 strategies per day
import datetime
TODAY = datetime.date.today().weekday()  # 0 = Monday, 6 = Sunday
RUN_BASELINE_TODAY = TODAY % 2 == 0      # Even days: run baseline
RUN_POLYMARKET_TODAY = TODAY % 2 == 1    # Odd days: run polymarket
