"""Generate modules/runtime.py, modules/signal.py, modules/swap_executor.py from ./_src_clean_swap.py."""
from __future__ import annotations

from pathlib import Path

SRC = Path("_src_clean_swap.py")
lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)


def concat_1_based(start: int, end_inclusive: int) -> str:
    return "".join(lines[start - 1 : end_inclusive])


def fix_nanolog(txt: str) -> str:
    return txt.replace("{_nanolog()}", "{runtime._nanolog()}")


def sorted_block() -> str:
    blk = concat_1_based(151, 236)
    blk = fix_nanolog(blk)
    blk = blk.replace("can_trade_asset(", "runtime.can_trade_asset(", 999)
    return blk


RUNTIME_HDR = '''\
"""Runtime: env, singletons, balances, state, take-profit, POL helpers.

Modular extraction from ``clean_swap`` (krantikaridev/nanoclaw V2).
"""
'''

SIGNAL_HDR = '''\
"""X-Signal equity eligibility, auto-USDC, planning, evaluation helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional, Sequence

from nanoclaw.config import X_SIGNAL
from nanoclaw.strategies.signal_equity_trader import (
    EquityTradePlan,
    FollowedEquity,
    SignalEquityTrader,
    SignalEquityTraderConfig,
)

from . import runtime
from .runtime import (
    AUTO_POPULATE_USDC_AMOUNT,
    Balances,
    FOLLOWED_EQUITIES_PATH,
    PER_ASSET_COOLDOWN_SECONDS,
    TradeDecision,
    USDC,
    X_SIGNAL_EQUITY_MIN_STRENGTH,
    X_SIGNAL_AUTO_USDC_TARGET,
    X_SIGNAL_EQUITY_TRADER,
    X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD,
    X_SIGNAL_FORCE_HIGH_CONVICTION,
    X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
    X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC,
    X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC,
    X_SIGNAL_USDC_MIN,
    X_SIGNAL_USDC_SAFE_FLOOR,
    X_SIGNAL_STRONG_THRESHOLD,
    X_SIGNAL_WMATIC_MIN_VALUE,
    approve_and_swap,
    get_balances,
    get_live_wmatic_price,
    get_token_balance,
    w3,
)

logger = logging.getLogger(__name__)

'''

ORCH_HDR = '''\
"""Orchestration: precedence, USDC-copy async wrapper, asyncio ``main``."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import time
from typing import Optional

from copy_trading import get_target_wallets
from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from swap_executor import approve_and_swap

from modules import attribution
from protection import record_buy

from . import runtime
from .runtime import (
    AUTO_TOPUP_POL,
    Balances,
    COOLDOWN_MINUTES,
    COPY_TRADE_PCT,
    ENABLE_USDC_COPY,
    ENABLE_X_SIGNAL_EQUITY,
    MIN_POL_FOR_GAS,
    PER_ASSET_COOLDOWN_MINUTES,
    PER_WALLET_COOLDOWN,
    STRONG_SIGNAL_TP,
    TAKE_PROFIT_PCT,
    TradeDecision,
    USDC_COPY_STRATEGY,
    WALLET,
    can_trade_wallet,
    create_lock,
    ensure_pol_for_trade,
    get_balances,
    get_gas_status,
    get_live_wmatic_price,
    get_pol_balance,
    has_active_lock,
    is_copy_trading_enabled,
    is_global_cooldown_active,
    load_state,
    mark_asset_traded,
    mark_wallet_traded,
    release_lock,
    save_state,
    write_portfolio_history_snapshot,
    w3,
)


def cs_check_exit_conditions() -> tuple[bool, str | None]:
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.check_exit_conditions()


def cs_evaluate_take_profit(current_price: float, state: dict):
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.evaluate_take_profit(current_price, state)


def cs_try_x_signal_equity_decision(balances: Balances, *, dry_run: bool = False):
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.try_x_signal_equity_decision(balances, dry_run=dry_run)


def cs_build_protection_exit_decision(
    reason: str,
    current_price: float,
    wmatic_balance: float,
    open_trade: Optional[dict],
) -> TradeDecision:
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.build_protection_exit_decision(
        reason, current_price, wmatic_balance, open_trade
    )


def cs_build_profit_exit_decision(profit_signal: dict, wmatic_balance: float) -> TradeDecision:
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.build_profit_exit_decision(profit_signal, wmatic_balance)


def cs_get_latest_open_trade(trade_log_file: str | None = None):
    clean_swap = importlib.import_module("clean_swap")
    if trade_log_file is None:
        return clean_swap.get_latest_open_trade()
    return clean_swap.get_latest_open_trade(trade_log_file)


'''


RUNTIME_PATCHES = (
    (
        'COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 7))',
        'COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 3))',
    ),
    (
        'X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = float(os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.80"))',
        'X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = float(os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.82"))',
    ),
    (
        'X_SIGNAL_STRONG_THRESHOLD = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.80"))',
        'X_SIGNAL_STRONG_THRESHOLD = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.82"))',
    ),
    (
        'os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.80")',
        'os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.82")',
    ),
)


def write_runtime() -> None:
    body = concat_1_based(1, 150) + concat_1_based(237, 692)
    for a, b in RUNTIME_PATCHES:
        body = body.replace(a, b, 1)
    Path("modules/runtime.py").write_text(RUNTIME_HDR + body, encoding="utf-8")


def write_signal() -> None:
    json_helpers = concat_1_based(130, 149)
    mid = concat_1_based(709, 919)
    mid = fix_nanolog(mid)
    mid = mid.replace("_log_trade_skipped(", "runtime._log_trade_skipped(", 999)
    tail = concat_1_based(921, 1292)
    tail = fix_nanolog(tail)
    tail = tail.replace("_log_trade_skipped(", "runtime._log_trade_skipped(", 999)
    Path("modules/signal.py").write_text(
        SIGNAL_HDR + json_helpers + "\n\n" + sorted_block() + "\n\n" + mid + "\n\n" + tail,
        encoding="utf-8",
    )


def orch_core() -> str:
    merged = (
        concat_1_based(695, 707)
        + concat_1_based(1293, 1323)
        + concat_1_based(1325, 1360)
        + concat_1_based(1361, 1446)
        + concat_1_based(1447, 1563)
    )
    merged = merged.replace("{_nanolog()}", "{runtime._nanolog()}", 999)
    merged = merged.replace("_log_trade_skipped(", "runtime._log_trade_skipped(", 999)
    merged = merged.replace("check_exit_conditions()", "cs_check_exit_conditions()", 999)
    merged = merged.replace("evaluate_take_profit(", "cs_evaluate_take_profit(", 999)
    merged = merged.replace(
        "build_protection_exit_decision(", "cs_build_protection_exit_decision(", 999
    )
    merged = merged.replace("build_profit_exit_decision(", "cs_build_profit_exit_decision(", 999)
    merged = merged.replace(
        "try_x_signal_equity_decision(", "cs_try_x_signal_equity_decision(", 999
    )
    merged = merged.replace("get_latest_open_trade(", "cs_get_latest_open_trade(", 999)
    merged = augment_success_block(merged)
    return merged


def augment_success_block(text: str) -> str:
    old = '''        if tx_hash:
            print("✅ Swap executed successfully!")'''
    new = '''        if tx_hash:
            attribution.notify_swap_success(decision=decision, tx_hash=tx_hash)
            print("✅ Swap executed successfully!")'''
    if old not in text:
        raise SystemExit("approve_and_swap success block not found — adjust augment_success_block")
    return text.replace(old, new, 1)


def write_orch() -> None:
    Path("modules/swap_executor.py").write_text(
        ORCH_HDR + orch_core(),
        encoding="utf-8",
    )


def main_builder() -> None:
    write_runtime()
    write_signal()
    write_orch()


if __name__ == "__main__":
    main_builder()
    print("wrote modules/runtime.py, modules/signal.py, modules/swap_executor.py")
