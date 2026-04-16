# config_real.py - All changeable parameters for v2 (Madan Pune)
TRADE_SIZE_USDT = 2.0                    # Increased as per your feedback
MAX_DAILY_LOSS_USDT = 10.0               # Testing allowance
MIN_EDGE_PCT = 3.0                       # Minimum edge to take trade
SIM_CONFIDENCE_THRESHOLD = 200000        # SIM capital above this = strong signal
ACTIVE_STRATEGIES = ["baseline", "polymarket"]  # Run only these two for now, alternate if needed
ALTERNATE_DAYS = False                   # Set True later when we have 4 strategies

# Wallet & RPC (static but easy to change)
WALLET_ADDRESS = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
RPC_URL = "https://polygon.drpc.org"
