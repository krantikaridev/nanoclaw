import random
from datetime import datetime

class BrainAgent:
    def __init__(self, min_trade=3.0, max_trade=8.0, strat2_weight=0.75):
        self.min_trade = min_trade
        self.max_trade = max_trade
        self.strat2_weight = strat2_weight
        self.recent_results = []  # store last 10 trade outcomes

    def decide_action(self, usdt_balance, pol_balance, recent_win_rate=0.5):
        # 1. If USDT too low → rebalance
        if usdt_balance < self.min_trade * 1.5:
            return "REBALANCE"

        # 2. If POL critical → skip (or auto top-up later)
        if pol_balance < 2.5:
            return "SKIP_POL_LOW"

        # 3. Choose strategy with weight
        if random.random() < self.strat2_weight:
            strat = "STRAT2"
            size = min(self.max_trade, max(self.min_trade, usdt_balance * 0.10))
        else:
            strat = "STRAT1"
            size = min(self.max_trade, max(self.min_trade, usdt_balance * 0.12))

        return f"TRADE_{strat}_{size:.2f}"

    def update_result(self, win: bool):
        self.recent_results.append(win)
        if len(self.recent_results) > 10:
            self.recent_results.pop(0)

# Example usage in clean_swap.py:
# brain = BrainAgent()
# action = brain.decide_action(usdt_balance, pol_balance)
