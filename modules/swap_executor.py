"""Orchestration: precedence, USDC-copy async wrapper, asyncio ``main``."""

from __future__ import annotations

import asyncio
import importlib
import time
from typing import Optional

import config as cfg
from config import (
    COPY_TRADE_AGGRESSIVE_THRESHOLD,
    MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE,
    MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION,
    MAIN_STRATEGY_CUT_LOSS_WMATIC_USD,
    MAIN_STRATEGY_MIN_USDT_RESERVE,
    MAIN_STRATEGY_RESERVE_SELL_FRACTION,
    MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD,
)
from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from swap_executor import approve_and_swap

from modules import attribution
from protection import record_buy

from . import runtime
from .runtime import (
    Balances,
    TradeDecision,
    USDC_COPY_STRATEGY,
    is_copy_trading_enabled,
    w3,
)

def _facade():
    """Tests monkeypatch attrs on ``clean_swap`` — always read knobs from that module."""
    return importlib.import_module("clean_swap")


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
        reason=reason or "UNKNOWN",
        current_price=current_price,
        wmatic_balance=wmatic_balance,
        open_trade=open_trade,
    )


def cs_build_profit_exit_decision(profit_signal: dict, wmatic_balance: float) -> TradeDecision:
    clean_swap = importlib.import_module("clean_swap")
    return clean_swap.build_profit_exit_decision(profit_signal, wmatic_balance)


def cs_get_latest_open_trade(trade_log_file: str | None = None):
    clean_swap = importlib.import_module("clean_swap")
    if trade_log_file is None:
        return clean_swap.get_latest_open_trade()
    return clean_swap.get_latest_open_trade(trade_log_file)


def select_copy_trade(balances: Balances, wallets: list[str]) -> TradeDecision:
    cs = _facade()
    active_wallets = [wallet for wallet in wallets if cs.can_trade_wallet(wallet)]
    if not active_wallets:
        cs._log_trade_skipped(f"cooldown (all wallets in {cs.PER_WALLET_COOLDOWN}s window)")
        return TradeDecision(message=f"TRADE SKIPPED: cooldown (all wallets in {cs.PER_WALLET_COOLDOWN}s window)")

    # FIXED SIZING: $12–$20 per signal (bug fix 2026-05-03); spend USDT leg only
    trade_size = cs.fixed_copy_trade_usd(balances.usdc, balances.usdt, cs.COPY_TRADE_PCT)
    trade_size = min(trade_size, balances.usdt)
    return TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message="🔄 REAL POLYCOPY MODE (28%) - Monitoring live wallets",
    )


async def evaluate_usdc_copy_trade(
    balances: Balances,
    wallets: list[str],
    *,
    strategy: Optional[USDCopyStrategy] = None,
) -> TradeDecision:
    cs = _facade()
    if not cs.ENABLE_USDC_COPY:
        return TradeDecision(message="ℹ️ USDC copy disabled")

    usdc_strategy = strategy if strategy is not None else USDC_COPY_STRATEGY
    plan = usdc_strategy.build_plan(
        usdc_balance=balances.usdc,
        usdt_balance=balances.usdt,
        wallets=wallets,
        wallet_address_for_gas=cs.WALLET,
        can_trade_wallet=cs.can_trade_wallet,
    )
    if not plan:
        return TradeDecision(message="ℹ️ No USDC-copy trade this cycle")

    cw = (
        str(plan.wallet).strip(),
        int(usdc_strategy.config.per_wallet_cooldown_seconds),
    ) if plan.wallet else None
    return TradeDecision(
        direction="USDC_TO_WMATIC",
        amount_in=plan.amount_in,
        trade_size=plan.trade_size,
        message=plan.message,
        cooldown_wallet=cw,
    )

def select_main_strategy_trade(
    balances: Balances,
    current_price: float,
) -> TradeDecision:
    cs = _facade()
    # FIXED SIZING: $12–$20 per signal (bug fix 2026-05-03)
    trade_size = cs.fixed_copy_trade_usd(balances.usdc, balances.usdt, cs.COPY_TRADE_PCT)
    trade_size = min(trade_size, balances.usdt)
    wmatic_value_usd = balances.wmatic * current_price

    if balances.usdt < MAIN_STRATEGY_MIN_USDT_RESERVE:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_RESERVE_SELL_FRACTION * 1e18),
            message=(
                f"🔄 USDT RESERVE PROTECTION: ${balances.usdt:.2f} < $"
                f"{MAIN_STRATEGY_MIN_USDT_RESERVE:.0f}"
            ),
        )

    if wmatic_value_usd > MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_RESERVE_SELL_FRACTION * 1e18),
            message=f"🔄 Taking profit (WMATIC high: ${wmatic_value_usd:.2f})",
        )

    if wmatic_value_usd < MAIN_STRATEGY_CUT_LOSS_WMATIC_USD and balances.wmatic > MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION * 1e18),
            message=f"🔄 Cutting loss (WMATIC down: ${wmatic_value_usd:.2f})",
        )

    return TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message=f"🔄 Buying WMATIC (hold preferred) | Size: ${trade_size:.2f}",
    )


def determine_trade_decision(
    state: dict,
    balances: Balances,
    current_price: float,
    *,
    dry_run: bool = False,
) -> TradeDecision:
    cs = _facade()
    print(
        f"\n{runtime._nanolog()}=== CYCLE {int(time.time())} | BALANCES: USDT=${balances.usdt:.2f} "
        f"USDC=${balances.usdc:.2f} WMATIC=${balances.wmatic:.2f} ==="
    )
    target_wallets_prelude = cs.get_target_wallets()
    print(
        f"🔍 BALANCES | USDT=${balances.usdt:.2f} USDC=${balances.usdc:.2f} "
        f"WMATIC≈{(balances.wmatic * current_price):.2f} USD | POL={balances.pol:.4f} "
        f"| copy_targets={len(target_wallets_prelude)}"
    )
    print(
        "🔍 DECISION PATH | precedence: "
        "PROTECTION → PROFIT_TAKE → X_SIGNAL_EQUITY → USDC_COPY | POLYCOPY → MAIN_STRATEGY"
    )
    print(
        f"{runtime._nanolog()}Runtime config | TAKE_PROFIT_PCT={cs.TAKE_PROFIT_PCT:.2f} "
        f"STRONG_SIGNAL_TP={cs.STRONG_SIGNAL_TP:.2f} "
        f"PER_ASSET_COOLDOWN_MINUTES={cs.PER_ASSET_COOLDOWN_MINUTES}"
    )

    if cs.COPY_TRADE_PCT >= COPY_TRADE_AGGRESSIVE_THRESHOLD:
        print(f"🔥 AGGRESSIVE MODE ACTIVE | COPY_TRADE_PCT={cs.COPY_TRADE_PCT:.2f}")

    should_force_sell, reason = cs_check_exit_conditions()
    if should_force_sell:
        print(f"🔍 DECISION PATH: PROTECTION ({reason})")
        return cs_build_protection_exit_decision(
            reason=reason or "UNKNOWN",
            current_price=current_price,
            wmatic_balance=balances.wmatic,
            open_trade=cs_get_latest_open_trade(),
        )

    should_take_profit, profit_signal = cs_evaluate_take_profit(current_price, state)
    if should_take_profit and profit_signal and balances.wmatic > 0:
        print(f"🔍 DECISION PATH: PROFIT_TAKE ({profit_signal.get('reason','')})")
        return cs_build_profit_exit_decision(profit_signal, balances.wmatic)

    if profit_signal and profit_signal["reason"] == "HOLD":
        print(f"📈 {profit_signal['message']}")

    if cs.ENABLE_X_SIGNAL_EQUITY:
        xd = cs_try_x_signal_equity_decision(balances, dry_run=dry_run)
        if xd and xd.should_execute:
            print("🔍 DECISION PATH: X_SIGNAL_EQUITY")
            return xd

    target_wallets = target_wallets_prelude or cs.get_target_wallets()
    if is_copy_trading_enabled() and target_wallets:
        if cs.ENABLE_USDC_COPY:
            plan = USDC_COPY_STRATEGY.build_plan(
                usdc_balance=balances.usdc,
                wallets=target_wallets,
                wallet_address_for_gas=cs.WALLET,
                can_trade_wallet=cs.can_trade_wallet,
                usdt_balance=balances.usdt,
            )
            if plan:  # try all eligible assets
                print(f"🔍 DECISION PATH: USDC_COPY | Size ~${plan.trade_size:.2f}")
                print(f"🟦 USDC COPY ACTIVE | Size: ${plan.trade_size:.2f}")
                cw_usdc = (
                    str(plan.wallet).strip(),
                    int(USDC_COPY_STRATEGY.config.per_wallet_cooldown_seconds),
                ) if plan.wallet else None
                return TradeDecision(
                    direction="USDC_TO_WMATIC",
                    amount_in=plan.amount_in,
                    trade_size=plan.trade_size,
                    message=plan.message,
                    cooldown_wallet=cw_usdc,
                )
            print("🟦 USDC COPY ACTIVE | No eligible copy-trade this cycle")
        else:
            print("🔍 DECISION PATH: POLYCOPY_TARGET_WALLETS")
            return select_copy_trade(balances, target_wallets)

    print(f"🔍 DECISION PATH: MAIN_STRATEGY (WMATIC≈${current_price:.4f})")
    return select_main_strategy_trade(balances, current_price)


async def main(*, dry_run: bool = False) -> None:
    cs = _facade()
    print(
        f"{runtime._nanolog()}SECRETS CHECK | All sensitive variables loaded from .env only (not hardcoded)"
    )
    state = cs.load_state()
    balances = cs.get_balances()
    print(f"{runtime._nanolog()}WALLET BALANCE | USDC=${balances.usdc:.2f} | Address={cs.WALLET}")
    print(
        f"Real USDT: {balances.usdt:.2f} | USDC: {balances.usdc:.2f} | "
        f"WMATIC: {balances.wmatic:.2f} | POL: {balances.pol:.2f}"
    )

    if cs.has_active_lock():
        print("⛔ Lock active — skipping")
        return

    cs.create_lock()
    try:
        current_price = cs.get_live_wmatic_price()
        cs.write_portfolio_history_snapshot(current_price)

        if cs.is_global_cooldown_active(state):
            lr = float(state.get("last_run") or 0.0)
            elapsed_s = max(0.0, time.time() - lr)
            remain_s = max(0.0, cs.COOLDOWN_MINUTES * 60 - elapsed_s)
            print(
                f"{runtime._nanolog()}skip cycle — global cooldown ~{remain_s:.0f}s left "
                f"(COOLDOWN_MINUTES={cs.COOLDOWN_MINUTES}; last_run was {elapsed_s:.0f}s ago)"
            )
            cs._log_trade_skipped(f"cooldown (global, ~{remain_s:.0f}s left)")
            return

        decision = await asyncio.to_thread(
            lambda: determine_trade_decision(state, balances, current_price, dry_run=dry_run)
        )
        cs.save_state(state)

        if decision.message:
            print(decision.message)

        if not decision.should_execute:
            cs._log_trade_skipped("protection/strategy returned no actionable trade")
            print("ℹ️ No actionable trade this cycle")
            return

        if dry_run:
            print(f"🧪 DRY RUN: would execute {decision.direction} for amount_in={decision.amount_in}")
            return

        pol_now = float(cs.get_pol_balance())
        if pol_now < float(cs.MIN_POL_FOR_GAS):
            if cs.AUTO_TOPUP_POL:
                topup_ok = await asyncio.to_thread(
                    cs.ensure_pol_for_trade,
                    float(cs.MIN_POL_FOR_GAS),
                )
                if not topup_ok:
                    cs._log_trade_skipped(f"POL low (auto top-up failed; need {cs.MIN_POL_FOR_GAS:.4f})")
                    print(f"{runtime._nanolog()}AUTO-POL failed — trade blocked (pol<{cs.MIN_POL_FOR_GAS:.3f})")
                    return
            else:
                cs._log_trade_skipped(f"POL low (have {pol_now:.4f}, need {cs.MIN_POL_FOR_GAS:.4f})")
                print(
                    f"{runtime._nanolog()}POL low (pol≈{pol_now:.4f} < {cs.MIN_POL_FOR_GAS:.4f}) "
                    "and AUTO_TOPUP_POL=false — trade blocked"
                )
                return

        gas_status = cs.get_gas_status()
        if not gas_status["ok"]:
            gas_gwei = float(gas_status.get("gas_gwei") or 0.0)
            if gas_gwei <= 400.0:
                print("⚠️ High gas but forcing trade (urgent mode)")
            else:
                cs._log_trade_skipped(
                    f"protection (gas high: {gas_status['gas_gwei']:.2f} gwei > {gas_status['max_gwei']:.2f})"
                )
                print(
                    "⛔ Gas protection active "
                    f"(gas {gas_status['gas_gwei']:.2f}/{gas_status['max_gwei']:.2f} gwei, "
                    f"POL {gas_status['pol_balance']:.4f}/{gas_status['min_pol_balance']:.4f})"
                )
                return

        if decision.direction == "USDT_TO_WMATIC":
            record_buy(current_price, decision.trade_size, "pending")

        tx_hash = await approve_and_swap(
            w3,
            cfg.get_resolved_key(),
            decision.amount_in,
            direction=decision.direction,
            token_in=decision.token_in,
            token_out=decision.token_out,
        )
        if tx_hash:
            attribution.notify_swap_success(decision=decision, tx_hash=tx_hash)
            print("✅ Swap executed successfully!")
            if decision.cooldown_asset:
                sym_ca, secs_a = decision.cooldown_asset
                cs.mark_asset_traded(sym_ca, cooldown_seconds=int(secs_a))
            if decision.cooldown_wallet and decision.cooldown_wallet[0]:
                wal_cw, secs_w = decision.cooldown_wallet
                cs.mark_wallet_traded(str(wal_cw).strip(), cooldown_seconds=int(secs_w))
        else:
            print(f"{runtime._nanolog()}Swap failed — per-asset/per-wallet cooldown not applied")

        state["last_run"] = time.time()
        cs.save_state(state)
        print(f"✅ Cycle done — next in ~{cs.COOLDOWN_MINUTES} min")
    finally:
        cs.release_lock()


