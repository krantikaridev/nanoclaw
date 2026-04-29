import asyncio
import json
import os
import time
import tempfile
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Sequence

from dotenv import load_dotenv
import argparse

try:
    from web3 import Web3
except ImportError:  # pragma: no cover - exercised in lightweight test environments
    class Web3:  # type: ignore[override]
        class HTTPProvider:  # type: ignore[override]
            def __init__(self, endpoint_uri: str | None) -> None:
                self.endpoint_uri = endpoint_uri

        def __init__(self, provider: "Web3.HTTPProvider") -> None:
            self.provider = provider
            self.eth = None

from constants import ERC20_ABI, USDC, USDT, WALLET, WMATIC
from nanoclaw.utils.gas_protector import GasProtector
from nanoclaw.strategies.usdc_copy import USDCopyStrategy
from nanoclaw.strategies.signal_equity_trader import (
    EquityTradePlan,
    SignalEquityTrader,
    SignalEquityTraderConfig,
    FollowedEquity,
)
from swap_executor import approve_and_swap
from copy_trading import get_target_wallets
from protection import check_exit_conditions, get_live_wmatic_price, record_buy

load_dotenv()
load_dotenv(".env.local", override=True)

LOCK_FILE = os.path.join(tempfile.gettempdir(), "nanoclaw.lock")
STATE_FILE = "bot_state.json"
TRADE_LOG_FILE = "trade_exits.json"

COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 7))
MIN_POL_FOR_GAS = float(os.getenv("MIN_POL_FOR_GAS", "0.05"))
COPY_TRADE_PCT = float(os.getenv("COPY_TRADE_PCT", "0.25"))
PER_WALLET_COOLDOWN = int(os.getenv("PER_WALLET_COOLDOWN", "180"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "5.0"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "8.0"))
STRONG_SIGNAL_TP = float(os.getenv("STRONG_SIGNAL_TP", "12.0"))
TAKE_PROFIT_SELL_PCT = float(os.getenv("TAKE_PROFIT_SELL_PCT", "0.45"))
STRONG_TP_SELL_PCT = float(os.getenv("STRONG_TP_SELL_PCT", "0.60"))
ENABLE_USDC_COPY = os.getenv("ENABLE_USDC_COPY", "false").lower() == "true"
ENABLE_X_SIGNAL_EQUITY = os.getenv("ENABLE_X_SIGNAL_EQUITY", "false").lower() == "true"
X_SIGNAL_EQUITY_MIN_STRENGTH = float(os.getenv("X_SIGNAL_EQUITY_MIN_STRENGTH", "0.70"))
FOLLOWED_EQUITIES_PATH = os.getenv("FOLLOWED_EQUITIES_PATH", "followed_equities.json")

WALLET_LAST_TRADE: Dict[str, float] = {}
ASSET_LAST_TRADE: Dict[str, float] = {}


@dataclass(frozen=True)
class Balances:
    usdt: float
    wmatic: float
    pol: float
    usdc: float = 0.0


@dataclass(frozen=True)
class TradeDecision:
    direction: Optional[str]
    amount_in: int = 0
    trade_size: float = 0.0
    message: str = ""
    token_in: Optional[str] = None
    token_out: Optional[str] = None

    @property
    def should_execute(self) -> bool:
        return bool(self.direction and self.amount_in > 0)


def build_web3_client(rpc_url: Optional[str] = None) -> Web3:
    return Web3(Web3.HTTPProvider(rpc_url or os.getenv("RPC")))


def build_gas_protector() -> GasProtector:
    return (
        GasProtector.builder()
        .with_max_gwei(float(os.getenv("MAX_GWEI", "80")))
        .with_urgent_gwei(float(os.getenv("URGENT_GWEI", "120")))
        .with_min_pol_balance(MIN_POL_FOR_GAS)
        .with_primary_rpc(os.getenv("RPC"))
        .with_fallback_rpcs(os.getenv("RPC_FALLBACKS", "").split(","))
        .with_retry_attempts(int(os.getenv("GAS_RPC_RETRY_ATTEMPTS", "2")))
        .build()
    )


def build_usdc_copy_strategy(protector: GasProtector) -> USDCopyStrategy:
    return (
        USDCopyStrategy.builder()
        .with_enabled(ENABLE_USDC_COPY)
        .with_copy_trade_pct(COPY_TRADE_PCT)
        .with_per_wallet_cooldown_seconds(PER_WALLET_COOLDOWN)
        .with_min_pol_for_gas(MIN_POL_FOR_GAS)
        .with_gas_protector(protector)
        .build()
    )


w3 = build_web3_client()
GAS_PROTECTOR = build_gas_protector()
USDC_COPY_STRATEGY = build_usdc_copy_strategy(GAS_PROTECTOR)
X_SIGNAL_EQUITY_TRADER = (
    SignalEquityTrader.builder()
    .with_enabled(ENABLE_X_SIGNAL_EQUITY)
    .with_followed_equities_path(FOLLOWED_EQUITIES_PATH)
    .with_usdc_address(USDC)
    .with_gas_protector(GAS_PROTECTOR)
    .build()
)


def is_copy_trading_enabled() -> bool:
    return os.getenv("COPY_TRADING_ENABLED", "true").lower() == "true"


def can_trade_wallet(
    wallet_address: str,
    now: Optional[float] = None,
    cooldown_seconds: int = PER_WALLET_COOLDOWN,
) -> bool:
    current_time = time.time() if now is None else now
    last = WALLET_LAST_TRADE.get(wallet_address, 0)
    return (current_time - last) > cooldown_seconds


def mark_wallet_traded(
    wallet_address: str,
    now: Optional[float] = None,
    cooldown_seconds: int = PER_WALLET_COOLDOWN,
) -> None:
    WALLET_LAST_TRADE[wallet_address] = time.time() if now is None else now
    print(f"📌 Wallet {wallet_address[:8]}... cooldown started ({cooldown_seconds}s)")


def can_trade_asset(symbol: str, now: Optional[float] = None, cooldown_seconds: int = 0) -> bool:
    current_time = time.time() if now is None else now
    last = ASSET_LAST_TRADE.get(symbol, 0)
    return (current_time - last) > int(cooldown_seconds)


def mark_asset_traded(symbol: str, now: Optional[float] = None, cooldown_seconds: int = 0) -> None:
    ASSET_LAST_TRADE[symbol] = time.time() if now is None else now
    if cooldown_seconds:
        print(f"📌 Asset {symbol} cooldown started ({int(cooldown_seconds)}s)")


def get_token_balance(
    token_address: str,
    decimals: int = 6,
    web3_client: Optional[Web3] = None,
    wallet_address: str = WALLET,
) -> float:
    client = web3_client or w3
    try:
        contract = client.eth.contract(address=token_address, abi=ERC20_ABI)
        return contract.functions.balanceOf(wallet_address).call() / (10**decimals)
    except Exception:
        return 0.0


def get_pol_balance(
    protector: GasProtector = GAS_PROTECTOR,
    wallet_address: str = WALLET,
) -> float:
    return protector.get_pol_balance(wallet_address)


def get_gas_status(
    urgent: bool = False,
    protector: GasProtector = GAS_PROTECTOR,
    wallet_address: str = WALLET,
) -> dict:
    return protector.get_safe_status(
        address=wallet_address,
        urgent=urgent,
        min_pol=MIN_POL_FOR_GAS,
    )


def get_balances() -> Balances:
    return Balances(
        usdt=get_token_balance(USDT, 6),
        wmatic=get_token_balance(WMATIC, 18),
        pol=get_pol_balance(),
        usdc=get_token_balance(USDC, 6),
    )


def load_state(path: str = STATE_FILE) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except Exception:
        return {"last_run": 0}


def save_state(state: dict, path: str = STATE_FILE) -> None:
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(state, file_handle, indent=2)


def has_active_lock(lock_file: str = LOCK_FILE, now: Optional[float] = None, lock_seconds: int = 15) -> bool:
    if not os.path.exists(lock_file):
        return False
    current_time = time.time() if now is None else now
    return (current_time - os.path.getmtime(lock_file)) < lock_seconds


def create_lock(lock_file: str = LOCK_FILE) -> None:
    with open(lock_file, "w", encoding="utf-8"):
        pass


def release_lock(lock_file: str = LOCK_FILE) -> None:
    if os.path.exists(lock_file):
        os.remove(lock_file)


def is_global_cooldown_active(
    state: dict,
    cooldown_minutes: int = COOLDOWN_MINUTES,
    now: Optional[float] = None,
) -> bool:
    current_time = time.time() if now is None else now
    return (current_time - state.get("last_run", 0)) < (cooldown_minutes * 60)


def get_latest_open_trade(trade_log_file: str = TRADE_LOG_FILE) -> Optional[dict]:
    if not os.path.exists(trade_log_file):
        return None

    try:
        with open(trade_log_file, "r", encoding="utf-8") as file_handle:
            trades = json.load(file_handle)
    except Exception:
        return None

    open_trades = [trade for trade in trades if trade.get("status") == "OPEN" and trade.get("buy_price")]
    return open_trades[-1] if open_trades else None


def evaluate_take_profit(current_price: float, state: dict) -> Tuple[bool, Optional[dict]]:
    trade = get_latest_open_trade()
    tracking = state.setdefault("profit_tracking", {})

    if not trade:
        tracking.clear()
        return False, None

    buy_price = float(trade["buy_price"])
    if buy_price <= 0:
        tracking.clear()
        return False, None

    tracked_buy_price = float(tracking.get("buy_price", 0) or 0)
    if tracked_buy_price != buy_price:
        tracking.clear()
        tracking["buy_price"] = buy_price
        tracking["peak_price"] = max(current_price, buy_price)

    peak_price = max(float(tracking.get("peak_price", buy_price)), current_price, buy_price)
    tracking["buy_price"] = buy_price
    tracking["peak_price"] = peak_price

    gain_pct = ((current_price - buy_price) / buy_price) * 100
    peak_gain_pct = ((peak_price - buy_price) / buy_price) * 100
    pullback_pct = ((peak_price - current_price) / peak_price) * 100 if peak_price > 0 else 0.0

    if gain_pct >= STRONG_SIGNAL_TP:
        return True, {
            "reason": "STRONG_TP_HIT",
            "message": (
                f"Strong TP hit | buy ${buy_price:.4f} -> now ${current_price:.4f} "
                f"({gain_pct:.2f}%) >= {STRONG_SIGNAL_TP:.2f}%"
            ),
            "sell_fraction": STRONG_TP_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    if gain_pct >= TAKE_PROFIT_PCT:
        return True, {
            "reason": "TP_HIT",
            "message": (
                f"Take-profit hit | buy ${buy_price:.4f} -> now ${current_price:.4f} "
                f"({gain_pct:.2f}%) >= {TAKE_PROFIT_PCT:.2f}%"
            ),
            "sell_fraction": TAKE_PROFIT_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    if peak_gain_pct >= TAKE_PROFIT_PCT and pullback_pct >= TRAILING_STOP_PCT:
        return True, {
            "reason": "TRAILING_STOP_HIT",
            "message": (
                f"Trailing stop hit | peak ${peak_price:.4f} ({peak_gain_pct:.2f}%) -> "
                f"now ${current_price:.4f} ({pullback_pct:.2f}% off peak)"
            ),
            "sell_fraction": TAKE_PROFIT_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    return False, {
        "reason": "HOLD",
        "message": (
            f"Holding open trade | buy ${buy_price:.4f} -> now ${current_price:.4f} "
            f"({gain_pct:.2f}%), peak ${peak_price:.4f} ({peak_gain_pct:.2f}%)"
        ),
        "sell_fraction": 0.0,
        "gain_pct": gain_pct,
        "peak_gain_pct": peak_gain_pct,
        "pullback_pct": pullback_pct,
    }


def build_protection_exit_decision(
    reason: str,
    current_price: float,
    wmatic_balance: float,
    open_trade: Optional[dict],
) -> TradeDecision:
    sell_fraction = 0.45

    if reason == "PER_TRADE_EXIT" and open_trade:
        buy_price = float(open_trade["buy_price"])
        gain_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
        sell_fraction = STRONG_TP_SELL_PCT if gain_pct >= STRONG_SIGNAL_TP else TAKE_PROFIT_SELL_PCT
        message = (
            f"🛡️ PROTECTION EXIT: {'strong TP hit' if gain_pct >= STRONG_SIGNAL_TP else 'TP hit'} | "
            f"buy ${buy_price:.4f} -> now ${current_price:.4f} "
            f"({gain_pct:.2f}%) | selling {sell_fraction * 100:.0f}% WMATIC"
        )
    else:
        message = f"🛡️ PROTECTION TRIGGERED: {reason} — Force selling"

    return TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(wmatic_balance * sell_fraction * 1e18),
        message=message,
    )


def build_profit_exit_decision(profit_signal: dict, wmatic_balance: float) -> TradeDecision:
    sell_fraction = min(1.0, max(0.1, float(profit_signal["sell_fraction"])))
    return TradeDecision(
        direction="WMATIC_TO_USDT",
        amount_in=int(wmatic_balance * sell_fraction * 1e18),
        message=(
            f"💰 EXIT SIGNAL: {profit_signal['reason']} | {profit_signal['message']} | "
            f"selling {sell_fraction * 100:.0f}% WMATIC"
        ),
    )


def select_copy_trade(balances: Balances, wallets: list[str]) -> TradeDecision:
    active_wallets = [wallet for wallet in wallets if can_trade_wallet(wallet)]
    if not active_wallets:
        return TradeDecision(message=f"⏳ All wallets in {PER_WALLET_COOLDOWN}s cooldown — skipping")

    trade_size = max(8.0, min(18.0, balances.usdt * COPY_TRADE_PCT))
    return TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message="🔄 REAL POLYCOPY MODE (20%) - Monitoring live wallets",
    )

def _pick_strongest_equity_signal(assets: Sequence[FollowedEquity]) -> Optional[FollowedEquity]:
    best: Optional[FollowedEquity] = None
    best_strength = 0.0
    for a in assets:
        strength = abs(float(a.signal_strength))
        if strength > best_strength:
            best_strength = strength
            best = a
    return best


def _tuned_signal_equity_trader(min_signal_strength: float) -> SignalEquityTrader:
    base_cfg = X_SIGNAL_EQUITY_TRADER.config
    tuned_cfg = SignalEquityTraderConfig(
        **{
            **base_cfg.__dict__,
            "enabled": True,
            "strong_signal_threshold": float(min_signal_strength),
        }
    )
    return SignalEquityTrader(
        config=tuned_cfg,
        gas_protector=X_SIGNAL_EQUITY_TRADER.gas_protector,
        usdc_address=X_SIGNAL_EQUITY_TRADER.usdc_address,
    )


def try_x_signal_equity_decision(balances: Balances) -> Optional[TradeDecision]:
    """Highest-priority iteration: eligible assets × SignalEquityTrader.build_plan; first plan wins."""
    if not ENABLE_X_SIGNAL_EQUITY:
        return None

    cfg: dict = {}
    try:
        with open(FOLLOWED_EQUITIES_PATH, "r", encoding="utf-8") as file_handle:
            cfg = json.load(file_handle) or {}
    except Exception:
        cfg = {}

    cfg_enabled = bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
    json_min = float(cfg.get("min_signal_strength", X_SIGNAL_EQUITY_MIN_STRENGTH) or X_SIGNAL_EQUITY_MIN_STRENGTH)
    min_strength = max(json_min, X_SIGNAL_EQUITY_MIN_STRENGTH)

    assets_seq = X_SIGNAL_EQUITY_TRADER.load_followed_equities()
    assets = sorted(
        assets_seq,
        key=lambda a: abs(float(a.signal_strength)),
        reverse=True,
    )
    eligible = [a for a in assets if abs(float(a.signal_strength)) >= min_strength]

    print(f"🟦 X-SIGNAL EQUITY CHECK | Checking {len(assets)} assets")
    if not cfg_enabled:
        print(f"🟦 X-SIGNAL EQUITY | No valid plan this cycle (reason: disabled in {FOLLOWED_EQUITIES_PATH})")
        return None
    if not assets:
        print(f"🟦 X-SIGNAL EQUITY | No valid plan this cycle (reason: no assets loaded)")
        return None
    if not eligible:
        print(
            f"🟦 X-SIGNAL EQUITY | No valid plan this cycle "
            f"(reason: no_asset_above_threshold (>={min_strength:.2f}))"
        )
        return None

    trader = _tuned_signal_equity_trader(min_strength)
    reason_parts: list[str] = []

    for a in eligible:
        sym = str(a.symbol).strip()
        sig = float(a.signal_strength)
        action_label = "BUY" if sig > 0 else "SELL"
        print(
            f"🟦 X-SIGNAL EQUITY ACTIVE | {sym} | Strength {sig:.3f} | Action: {action_label}"
        )
        equity_bal = get_token_balance(a.token_address, int(a.decimals))
        plan = trader.build_plan(
            symbol=sym,
            token_address=str(a.token_address).strip(),
            token_decimals=int(a.decimals),
            signal_strength=sig,
            earnings_proximity_days=a.earnings_days,
            current_price_usd=a.current_price_usd,
            usdc_balance=balances.usdc,
            equity_balance=equity_bal,
            wallet_address_for_gas=WALLET,
            can_trade_asset=can_trade_asset,
            mark_asset_traded=mark_asset_traded,
        )
        if plan:
            return TradeDecision(
                direction=plan.direction,
                amount_in=plan.amount_in,
                trade_size=plan.trade_size,
                message=plan.message,
                token_in=plan.token_in,
                token_out=plan.token_out,
            )
        hints: list[str] = []
        if balances.usdc <= 0 and sig > 0:
            hints.append("zero_usdc_for_buy_path")
        if equity_bal <= 0 and sig < 0:
            hints.append("zero_equity_balance_for_sell_path")
        if not trader.gas_protector.get_safe_status(
            address=WALLET, urgent=False, min_pol=float(trader.config.min_pol_for_gas)
        ).get("ok", False):
            hints.append("gas_or_pol_guard_blocked")
        if not can_trade_asset(
            sym,
            now=None,
            cooldown_seconds=int(trader.config.per_asset_cooldown_seconds),
        ):
            hints.append(f"cooldown_seconds={trader.config.per_asset_cooldown_seconds}s")
        if not hints:
            hints.append(f"risk_filters_or_router_none_for_{sym}")
        reason_parts.append("; ".join(dict.fromkeys(hints)))

    reason = (
        " | ".join(reason_parts[:3])
        + (f" …(+{len(reason_parts)-3}_more)" if len(reason_parts) > 3 else "")
    )
    print(f"🟦 X-SIGNAL EQUITY | No valid plan this cycle (reason: {reason})")
    return None


def evaluate_x_signal_equity_trade(
    balances: Balances,
    *,
    trader: SignalEquityTrader = X_SIGNAL_EQUITY_TRADER,
) -> Optional[EquityTradePlan]:
    if not ENABLE_X_SIGNAL_EQUITY:
        return None

    assets = trader.load_followed_equities()
    if not assets:
        return None

    best = _pick_strongest_equity_signal(assets)
    if not best:
        return None

    symbol = str(best.symbol).strip()
    token_address = str(best.token_address).strip()
    decimals = int(best.decimals)
    signal_strength = float(best.signal_strength)
    earnings_days_f = best.earnings_days
    current_price_f = best.current_price_usd

    equity_balance = get_token_balance(token_address, decimals)
    min_s = max(
        float(trader.config.strong_signal_threshold),
        X_SIGNAL_EQUITY_MIN_STRENGTH,
    )
    tuned = _tuned_signal_equity_trader(min_s)
    return tuned.build_plan(
        symbol=symbol,
        token_address=token_address,
        token_decimals=decimals,
        signal_strength=signal_strength,
        earnings_proximity_days=earnings_days_f,
        current_price_usd=current_price_f,
        usdc_balance=balances.usdc,
        equity_balance=equity_balance,
        wallet_address_for_gas=WALLET,
        can_trade_asset=can_trade_asset,
        mark_asset_traded=mark_asset_traded,
    )


async def evaluate_usdc_copy_trade(
    balances: Balances,
    wallets: list[str],
    *,
    strategy: Optional[USDCopyStrategy] = None,
) -> TradeDecision:
    if not ENABLE_USDC_COPY:
        return TradeDecision(message="ℹ️ USDC copy disabled")

    usdc_strategy = strategy or build_usdc_copy_strategy()
    plan = usdc_strategy.build_plan(
        usdc_balance=balances.usdc,
        wallets=wallets,
        wallet_address_for_gas=WALLET,
        can_trade_wallet=can_trade_wallet,
        mark_wallet_traded=mark_wallet_traded,
    )
    if not plan:
        return TradeDecision(message="ℹ️ No USDC-copy trade this cycle")

    return TradeDecision(
        direction="USDC_TO_WMATIC",
        amount_in=plan.amount_in,
        trade_size=plan.trade_size,
        message=plan.message,
    )


def select_main_strategy_trade(
    balances: Balances,
    current_price: float,
) -> TradeDecision:
    trade_size = max(15.0, min(35.0, balances.usdt * 0.28))
    wmatic_value_usd = balances.wmatic * current_price

    if balances.usdt < 25:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * 0.45 * 1e18),
            message=f"🔄 USDT RESERVE PROTECTION: ${balances.usdt:.2f} < $25",
        )

    if wmatic_value_usd > 52:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * 0.45 * 1e18),
            message=f"🔄 Taking profit (WMATIC high: ${wmatic_value_usd:.2f})",
        )

    if wmatic_value_usd < 40 and balances.wmatic > 50:
        return TradeDecision(
            direction="WMATIC_TO_USDT",
            amount_in=int(balances.wmatic * 0.28 * 1e18),
            message=f"🔄 Cutting loss (WMATIC down: ${wmatic_value_usd:.2f})",
        )

    return TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message=f"🔄 Buying WMATIC (hold preferred) | Size: ${trade_size:.2f}",
    )


def determine_trade_decision(state: dict, balances: Balances, current_price: float) -> TradeDecision:
    target_wallets_prelude = get_target_wallets()
    print(
        f"🔍 BALANCES | USDT=${balances.usdt:.2f} USDC=${balances.usdc:.2f} "
        f"WMATIC≈{(balances.wmatic * current_price):.2f} USD | POL={balances.pol:.4f} "
        f"| copy_targets={len(target_wallets_prelude)}"
    )
    print(
        "🔍 DECISION PATH | precedence: "
        "PROTECTION → PROFIT_TAKE → X_SIGNAL_EQUITY → USDC_COPY | POLYCOPY → MAIN_STRATEGY"
    )

    if COPY_TRADE_PCT >= 0.20:
        print(f"🔥 AGGRESSIVE MODE ACTIVE | COPY_TRADE_PCT={COPY_TRADE_PCT:.2f}")

    should_force_sell, reason = check_exit_conditions()
    if should_force_sell:
        print(f"🔍 DECISION PATH: PROTECTION ({reason})")
        return build_protection_exit_decision(
            reason=reason or "UNKNOWN",
            current_price=current_price,
            wmatic_balance=balances.wmatic,
            open_trade=get_latest_open_trade(),
        )

    should_take_profit, profit_signal = evaluate_take_profit(current_price, state)
    if should_take_profit and profit_signal and balances.wmatic > 0:
        print(f"🔍 DECISION PATH: PROFIT_TAKE ({profit_signal.get('reason','')})")
        return build_profit_exit_decision(profit_signal, balances.wmatic)

    if profit_signal and profit_signal["reason"] == "HOLD":
        print(f"📈 {profit_signal['message']}")

    if ENABLE_X_SIGNAL_EQUITY:
        xd = try_x_signal_equity_decision(balances)
        if xd and xd.should_execute:
            print("🔍 DECISION PATH: X_SIGNAL_EQUITY")
            return xd

    target_wallets = target_wallets_prelude or get_target_wallets()
    if is_copy_trading_enabled() and target_wallets:
        if ENABLE_USDC_COPY:
            plan = USDC_COPY_STRATEGY.build_plan(
                usdc_balance=balances.usdc,
                wallets=target_wallets,
                wallet_address_for_gas=WALLET,
                can_trade_wallet=can_trade_wallet,
                mark_wallet_traded=mark_wallet_traded,
            )
            if plan:
                print(f"🔍 DECISION PATH: USDC_COPY | Size ~${plan.trade_size:.2f}")
                print(f"🟦 USDC COPY ACTIVE | Size: ${plan.trade_size:.2f}")
                return TradeDecision(
                    direction="USDC_TO_WMATIC",
                    amount_in=plan.amount_in,
                    trade_size=plan.trade_size,
                    message=plan.message,
                )
            print("🟦 USDC COPY ACTIVE | No eligible copy-trade this cycle")
        else:
            print("🔍 DECISION PATH: POLYCOPY_TARGET_WALLETS")
            return select_copy_trade(balances, target_wallets)

    print(f"🔍 DECISION PATH: MAIN_STRATEGY (WMATIC≈${current_price:.4f})")
    return select_main_strategy_trade(balances, current_price)


async def main(*, dry_run: bool = False) -> None:
    state = load_state()
    balances = get_balances()

    print(
        f"Real USDT: {balances.usdt:.2f} | USDC: {balances.usdc:.2f} | "
        f"WMATIC: {balances.wmatic:.2f} | POL: {balances.pol:.2f}"
    )

    if has_active_lock():
        print("⛔ Lock active — skipping")
        return

    create_lock()
    try:
        if is_global_cooldown_active(state):
            print(f"⏳ Copy cooldown active ({COOLDOWN_MINUTES * 60}s) — skipping")
            return

        gas_status = get_gas_status()
        if not gas_status["ok"]:
            gas_gwei = float(gas_status.get("gas_gwei") or 0.0)
            if gas_gwei <= 400.0:
                print("⚠️ High gas but forcing trade (urgent mode)")
            else:
                print(
                    "⛔ Gas protection active "
                    f"(gas {gas_status['gas_gwei']:.2f}/{gas_status['max_gwei']:.2f} gwei, "
                    f"POL {gas_status['pol_balance']:.4f}/{gas_status['min_pol_balance']:.4f})"
                )
                return

        current_price = get_live_wmatic_price()
        decision = await asyncio.to_thread(determine_trade_decision, state, balances, current_price)
        save_state(state)

        if decision.message:
            print(decision.message)

        if not decision.should_execute:
            print("ℹ️ No actionable trade this cycle")
            return

        if dry_run:
            print(f"🧪 DRY RUN: would execute {decision.direction} for amount_in={decision.amount_in}")
            return

        if decision.direction == "USDT_TO_WMATIC":
            record_buy(current_price, decision.trade_size, "pending")

        tx_hash = await approve_and_swap(
            w3,
            os.getenv("POLYGON_PRIVATE_KEY") or os.getenv("PRIVATE_KEY"),
            decision.amount_in,
            direction=decision.direction,
            token_in=decision.token_in,
            token_out=decision.token_out,
        )
        if tx_hash:
            print("✅ Swap executed successfully!")
        else:
            print("⚠️ Swap failed")

        state["last_run"] = time.time()
        save_state(state)
        print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")
    finally:
        release_lock()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Evaluate decision-making without submitting swaps")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
