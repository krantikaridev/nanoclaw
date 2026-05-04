#!/usr/bin/env python3
"""Nanoclaw V2 — thin façade; implementation in ``modules.runtime``, ``modules.signal``, ``modules.swap_executor``."""

from __future__ import annotations

import os
os.environ.setdefault("RPC_URL", "https://polygon-rpc.com")
os.environ.setdefault("WEB3_PROVIDER_URI", "https://polygon-rpc.com")

import argparse
import asyncio
import logging
import time

from config import PRIVATE_KEY, UNISWAP_V3_SWAP_ROUTER
from copy_trading import get_target_wallets
from nanoclaw.strategies.signal_equity_trader import EquityTradePlan, FollowedEquity
from swap_executor import _force_max_approval

from constants import ERC20_ABI, LOG_PREFIX, USDC, USDT, WALLET, WMATIC
from modules import runtime
from modules import signal
from modules.swap_executor import (
    determine_trade_decision,
    evaluate_usdc_copy_trade,
    main,
    select_copy_trade,
    select_main_strategy_trade,
)
from protection import check_exit_conditions, get_live_wmatic_price, record_buy


# --- Re-export infra + constants expected by cron/tests/docs ---
AUTO_POPULATE_USDC_AMOUNT = runtime.AUTO_POPULATE_USDC_AMOUNT
AUTO_TOPUP_POL = runtime.AUTO_TOPUP_POL
AUTO_USDC_FOR_X_SIGNAL_MIN_USDC = runtime.AUTO_USDC_FOR_X_SIGNAL_MIN_USDC
AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE = runtime.AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE
ASSET_LAST_TRADE = runtime.ASSET_LAST_TRADE
Balances = runtime.Balances
COPY_TRADE_PCT = runtime.COPY_TRADE_PCT
MAX_GWEI = runtime.MAX_GWEI
FIXED_TRADE_USD_MIN = runtime.FIXED_TRADE_USD_MIN
FIXED_TRADE_USD_MAX = runtime.FIXED_TRADE_USD_MAX
# Copy/main: runtime.fixed_copy_trade_usd (FIXED_TRADE_USD_*); X-signal: dynamic band + signal in signal_equity_trader._compute_trade_size
fixed_copy_trade_usd = runtime.fixed_copy_trade_usd
COOLDOWN_MINUTES = runtime.COOLDOWN_MINUTES
ENABLE_USDC_COPY = runtime.ENABLE_USDC_COPY
ENABLE_X_SIGNAL_EQUITY = runtime.ENABLE_X_SIGNAL_EQUITY
FOLLOWED_EQUITIES_PATH = runtime.FOLLOWED_EQUITIES_PATH
GAS_PROTECTOR = runtime.GAS_PROTECTOR
LOCK_FILE = runtime.LOCK_FILE
MIN_POL_FOR_GAS = runtime.MIN_POL_FOR_GAS
PER_ASSET_COOLDOWN_MINUTES = runtime.PER_ASSET_COOLDOWN_MINUTES
PER_ASSET_COOLDOWN_SECONDS = runtime.PER_ASSET_COOLDOWN_SECONDS
PER_WALLET_COOLDOWN = runtime.PER_WALLET_COOLDOWN
POL_TOPUP_AMOUNT = runtime.POL_TOPUP_AMOUNT
POL_USD_PRICE = runtime.POL_USD_PRICE
PORTFOLIO_HISTORY_FILE = runtime.PORTFOLIO_HISTORY_FILE
STATE_FILE = runtime.STATE_FILE
STRONG_SIGNAL_TP = runtime.STRONG_SIGNAL_TP
STRONG_TP_SELL_PCT = runtime.STRONG_TP_SELL_PCT
TAKE_PROFIT_PCT = runtime.TAKE_PROFIT_PCT
TAKE_PROFIT_SELL_PCT = runtime.TAKE_PROFIT_SELL_PCT
TRADE_LOG_FILE = runtime.TRADE_LOG_FILE
TRAILING_STOP_PCT = runtime.TRAILING_STOP_PCT
TradeDecision = runtime.TradeDecision
USDC_COPY_STRATEGY = runtime.USDC_COPY_STRATEGY
WALLET_LAST_TRADE = runtime.WALLET_LAST_TRADE
X_SIGNAL_AUTO_USDC_TARGET = runtime.X_SIGNAL_AUTO_USDC_TARGET
X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT = runtime.X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT
X_SIGNAL_EQUITY_MIN_STRENGTH = runtime.X_SIGNAL_EQUITY_MIN_STRENGTH
X_SIGNAL_EQUITY_TRADER = runtime.X_SIGNAL_EQUITY_TRADER
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = runtime.X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD
X_SIGNAL_FORCE_HIGH_CONVICTION = runtime.X_SIGNAL_FORCE_HIGH_CONVICTION
X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = runtime.X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC = runtime.X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC = runtime.X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC
X_SIGNAL_MAX_EARNINGS_DAYS = runtime.X_SIGNAL_MAX_EARNINGS_DAYS
X_SIGNAL_STRONG_THRESHOLD = runtime.X_SIGNAL_STRONG_THRESHOLD
X_SIGNAL_USDC_MIN = runtime.X_SIGNAL_USDC_MIN
X_SIGNAL_USDC_SAFE_FLOOR = runtime.X_SIGNAL_USDC_SAFE_FLOOR
X_SIGNAL_WMATIC_MIN_VALUE = runtime.X_SIGNAL_WMATIC_MIN_VALUE
w3 = runtime.w3
build_gas_protector = runtime.build_gas_protector
build_profit_exit_decision = runtime.build_profit_exit_decision
build_protection_exit_decision = runtime.build_protection_exit_decision
build_usdc_copy_strategy = runtime.build_usdc_copy_strategy
build_web3_client = runtime.build_web3_client
can_trade_asset = runtime.can_trade_asset
can_trade_wallet = runtime.can_trade_wallet
create_lock = runtime.create_lock
ensure_pol_for_trade = runtime.ensure_pol_for_trade
evaluate_take_profit = runtime.evaluate_take_profit
get_balances = runtime.get_balances
get_gas_status = runtime.get_gas_status
get_latest_open_trade = runtime.get_latest_open_trade
get_pol_balance = runtime.get_pol_balance
get_token_balance = runtime.get_token_balance
has_active_lock = runtime.has_active_lock
is_copy_trading_enabled = runtime.is_copy_trading_enabled
is_global_cooldown_active = runtime.is_global_cooldown_active
load_state = runtime.load_state
mark_asset_traded = runtime.mark_asset_traded
mark_wallet_traded = runtime.mark_wallet_traded
release_lock = runtime.release_lock
save_state = runtime.save_state
write_portfolio_history_snapshot = runtime.write_portfolio_history_snapshot
_effective_take_profit_thresholds = runtime._effective_take_profit_thresholds
_log_trade_skipped = runtime._log_trade_skipped

# Signal / X-equity hooks
_load_followed_equities_json_dict = signal._load_followed_equities_json_dict
_order_eligible_x_signal_candidates = signal._order_eligible_x_signal_candidates
_project_balances_after_auto_usdc = signal._project_balances_after_auto_usdc
_sorted_and_eligible_equities = signal._sorted_and_eligible_equities
_strong_x_signal_buy_present = signal.strong_buy_detector
_tuned_signal_equity_trader = signal._tuned_signal_equity_trader
_effective_equity_signal_min = signal._effective_equity_signal_min
_effective_floor_for_equity = signal._effective_floor_for_equity
ensure_usdc_for_x_signal = signal.ensure_usdc_for_x_signal
evaluate_x_signal_equity_trade = signal.evaluate_x_signal_equity_trade
try_x_signal_equity_decision = signal.try_x_signal_equity_decision

if __name__ == "__main__":
    if not logging.root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    if PRIVATE_KEY:
        print("🚀 Running one-time max approval at startup...")
        _force_max_approval(w3, PRIVATE_KEY, UNISWAP_V3_SWAP_ROUTER)
        print("✅ Startup approval complete. Bot ready.")
    else:
        print("⚠️ Startup approval skipped: private key not configured.")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate decision-making without submitting swaps",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
