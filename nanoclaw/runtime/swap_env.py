"""
Environment-derived defaults for the swap bot entry (`clean_swap.py`).

Imported after `load_dotenv()` so `.env` values apply. These keys are
swap-runner-specific today; a single shared `nanoclaw.settings` (or similar)
could unify env loading across CLI tools later without changing names here.
"""

from __future__ import annotations

import os

COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 7))
PER_ASSET_COOLDOWN_MINUTES = int(os.getenv("PER_ASSET_COOLDOWN_MINUTES", "30"))
PER_ASSET_COOLDOWN_SECONDS = PER_ASSET_COOLDOWN_MINUTES * 60
POL_USD_PRICE = float(os.getenv("POL_USD_PRICE", "0.10"))
MIN_POL_FOR_GAS = float(os.getenv("MIN_POL_FOR_GAS", "0.005"))
AUTO_TOPUP_POL = os.getenv("AUTO_TOPUP_POL", "true").lower() == "true"
POL_TOPUP_AMOUNT = float(os.getenv("POL_TOPUP_AMOUNT", "0.03"))
COPY_TRADE_PCT = float(os.getenv("COPY_TRADE_PCT", "0.25"))
PER_WALLET_COOLDOWN = int(os.getenv("PER_WALLET_COOLDOWN", "180"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "5.0"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "8.0"))
STRONG_SIGNAL_TP = float(os.getenv("STRONG_SIGNAL_TP", "12.0"))
TAKE_PROFIT_SELL_PCT = float(os.getenv("TAKE_PROFIT_SELL_PCT", "0.45"))
STRONG_TP_SELL_PCT = float(os.getenv("STRONG_TP_SELL_PCT", "0.60"))
ENABLE_USDC_COPY = os.getenv("ENABLE_USDC_COPY", "false").lower() == "true"
ENABLE_X_SIGNAL_EQUITY = os.getenv("ENABLE_X_SIGNAL_EQUITY", "false").lower() == "true"
X_SIGNAL_EQUITY_MIN_STRENGTH = float(os.getenv("X_SIGNAL_EQUITY_MIN_STRENGTH", "0.60"))
X_SIGNAL_MAX_EARNINGS_DAYS = float(os.getenv("X_SIGNAL_MAX_EARNINGS_DAYS", "5.0"))
X_SIGNAL_FORCE_HIGH_CONVICTION = os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION", "true").lower() == "true"
X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = float(os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.80"))
X_SIGNAL_STRONG_THRESHOLD = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.80"))
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = float(
    os.getenv(
        "X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD",
        os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.80"),
    )
)
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC = float(os.getenv("X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC", "8.0"))
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC = float(os.getenv("X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC", "12.0"))
X_SIGNAL_DYNAMIC_TIER_HIGH_MIN = float(os.getenv("X_SIGNAL_DYNAMIC_TIER_HIGH_MIN", "0.90"))
X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH = float(os.getenv("X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH", "12.0"))
X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE = float(os.getenv("X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE", "10.0"))
X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE = float(os.getenv("X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE", "8.0"))
FOLLOWED_EQUITIES_PATH = os.getenv("FOLLOWED_EQUITIES_PATH", "followed_equities.json")
# Iron-fenced USDC population to prevent zero-USDC blocker.
# Keep env precedence aligned with SignalEquityTraderBuilder to avoid sizing mismatches.
X_SIGNAL_USDC_MIN = float(
    os.getenv(
        "X_SIGNAL_EQUITY_MIN_TRADE",
        os.getenv("X_SIGNAL_USDC_MIN", os.getenv("AUTO_USDC_FOR_X_SIGNAL_MIN_USDC", "5.0")),
    )
)
X_SIGNAL_WMATIC_MIN_VALUE = float(
    os.getenv("X_SIGNAL_WMATIC_MIN_VALUE", os.getenv("AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE", "15.0"))
)
AUTO_POPULATE_USDC_AMOUNT = float(os.getenv("AUTO_POPULATE_USDC_AMOUNT", "20.0"))
# Back-compat aliases (older env names referenced in docs/tests).
AUTO_USDC_FOR_X_SIGNAL_MIN_USDC = float(os.getenv("AUTO_USDC_FOR_X_SIGNAL_MIN_USDC", str(X_SIGNAL_USDC_MIN)))
AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE = float(
    os.getenv("AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE", str(X_SIGNAL_WMATIC_MIN_VALUE))
)
# When true (default): try assets off per-asset cooldown before higher-signal assets still cooling down.
X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT = (
    os.getenv("X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT", "true").lower() == "true"
)
# Proactive USDC maintenance for X-Signal equity trading.
X_SIGNAL_USDC_SAFE_FLOOR = float(os.getenv("X_SIGNAL_USDC_SAFE_FLOOR", "20.0"))
X_SIGNAL_AUTO_USDC_TARGET = float(os.getenv("X_SIGNAL_AUTO_USDC_TARGET", "25.0"))
