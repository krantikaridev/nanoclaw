import asyncio
import csv
import json
import os
import time
import tempfile
from datetime import datetime, timezone
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

from constants import ERC20_ABI, LOG_PREFIX, USDC, USDT, WALLET, WMATIC
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
# Optional local override file (kept for VM/operator compatibility).
load_dotenv(".env.local", override=True)

LOCK_FILE = os.path.join(tempfile.gettempdir(), "nanoclaw.lock")
STATE_FILE = "bot_state.json"
TRADE_LOG_FILE = "trade_exits.json"
PORTFOLIO_HISTORY_FILE = "portfolio_history.csv"

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


def _nanolog() -> str:
    p = (LOG_PREFIX or "").strip()
    return f"{p} " if p else ""


def _effective_take_profit_thresholds() -> tuple[float, float]:
    """
    Keep two-tier TP valid even when env values are misconfigured.
    Strong TP must always be greater than base TP.
    """
    base_tp = float(TAKE_PROFIT_PCT)
    strong_tp = float(STRONG_SIGNAL_TP)
    if strong_tp <= base_tp:
        strong_tp = base_tp + 4.0
    return base_tp, strong_tp


def _log_trade_skipped(reason: str) -> None:
    print(f"{_nanolog()}TRADE SKIPPED: {reason}")


def _load_followed_equities_json_dict() -> dict:
    try:
        with open(FOLLOWED_EQUITIES_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _effective_equity_signal_min(cfg: dict) -> float:
    json_floor = float(
        cfg.get("min_signal_strength", X_SIGNAL_EQUITY_MIN_STRENGTH) or X_SIGNAL_EQUITY_MIN_STRENGTH
    )
    return max(json_floor, X_SIGNAL_EQUITY_MIN_STRENGTH)


def _sorted_and_eligible_equities(
    assets_seq: Sequence[FollowedEquity],
    min_strength: float,
) -> tuple[list[FollowedEquity], list[FollowedEquity]]:
    assets_list = sorted(
        assets_seq,
        key=lambda a: abs(float(a.signal_strength)),
        reverse=True,
    )
    eligible: list[FollowedEquity] = []
    for a in assets_list:
        # Tier 1: explicit per-asset min_signal_strength (including 0.0) must be respected.
        asset_floor_raw = getattr(a, "min_signal_strength", None)
        effective_floor = float(min_strength) if asset_floor_raw is None else float(asset_floor_raw)
        if abs(float(a.signal_strength)) >= effective_floor:
            eligible.append(a)
    return assets_list, eligible


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
    direction: Optional[str] = None
    amount_in: int = 0
    trade_size: float = 0.0
    message: str = ""
    token_in: Optional[str] = None
    token_out: Optional[str] = None
    cooldown_asset: Optional[Tuple[str, int]] = None
    cooldown_wallet: Optional[Tuple[str, int]] = None

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
    .with_per_asset_cooldown_seconds(PER_ASSET_COOLDOWN_SECONDS)
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


def ensure_pol_for_trade(min_pol: float = 0.025) -> bool:
    current_pol = float(get_pol_balance())
    if current_pol >= float(min_pol):
        return True

    key = os.getenv("POLYGON_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
    if not key:
        print(f"{_nanolog()}AUTO-POL skipped — no private key")
        return False

    print(f"🔄 AUTO-POL | Topping up 0.03 POL (current: {current_pol})")
    target_pol = float(POL_TOPUP_AMOUNT)
    needed_pol = max(0.0, float(min_pol) - current_pol)
    # Ensure we target enough unwrap to clear the runtime min_pol floor, not just POL_TOPUP_AMOUNT.
    desired_topup_pol = max(target_pol, needed_pol + 0.002)
    balances = get_balances()
    usdt_swap_amount = min(8.0, float(balances.usdt) * 0.95)

    async def _swap_usdt_to_wmatic(amount_units: int) -> bool:
        if amount_units <= 0:
            return False
        tx_hash = await approve_and_swap(
            w3,
            key,
            amount_units,
            direction="USDT_TO_WMATIC",
        )
        return tx_hash is not None

    def _run(coro):
        return asyncio.run(coro)

    if balances.wmatic < desired_topup_pol and usdt_swap_amount >= 6.0:
        ok = _run(_swap_usdt_to_wmatic(int(usdt_swap_amount * 1_000_000)))
        if not ok:
            print(f"{_nanolog()}AUTO-POL warn — USDT→WMATIC leg failed, trying WMATIC unwrap fallback")
        balances = get_balances()

    unwrap_pol = min(desired_topup_pol, float(balances.wmatic) * 0.95)
    if unwrap_pol <= 0:
        print(f"{_nanolog()}AUTO-POL skipped — insufficient WMATIC/USDT for top-up")
        return False

    try:
        withdraw_abi = [
            {
                "constant": False,
                "inputs": [{"name": "wad", "type": "uint256"}],
                "name": "withdraw",
                "outputs": [],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function",
            }
        ]
        amount_wei = int(unwrap_pol * 1e18)
        contract = w3.eth.contract(address=WMATIC, abi=withdraw_abi)
        nonce = w3.eth.get_transaction_count(WALLET)
        tx = contract.functions.withdraw(amount_wei).build_transaction(
            {
                "from": WALLET,
                "nonce": nonce,
                "chainId": int(getattr(w3.eth, "chain_id", 137) or 137),
                "gas": 140_000,
                "gasPrice": int(w3.eth.gas_price),
            }
        )
        signed = w3.eth.account.sign_transaction(tx, private_key=key)
        raw_tx = signed.raw_transaction
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if int(receipt.get("status", 0)) != 1:
            print(f"{_nanolog()}AUTO-POL failed — WMATIC unwrap reverted")
            return False
        final_pol = float(get_pol_balance())
        if final_pol >= float(min_pol):
            print("✅ AUTO-POL | Top-up successful")
            return True
        print(
            f"{_nanolog()}AUTO-POL failed — POL still low "
            f"(pol≈{final_pol:.4f}, need≥{float(min_pol):.4f})"
        )
        return False
    except Exception as e:
        print(f"{_nanolog()}AUTO-POL failed — {e}")
        return False


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


def _portfolio_history_header() -> list[str]:
    return ["timestamp", "usdt", "usdc", "wmatic", "pol", "pol_usd_price", "total_value"]


def write_portfolio_history_snapshot(current_price: float) -> None:
    """
    Persist portfolio history from real on-chain balances.
    This avoids stale cached totals and keeps wallet value accurate in CSV.
    """
    usdt = get_token_balance(USDT, 6)
    wmatic = get_token_balance(WMATIC, 18)
    pol = get_pol_balance()
    usdc = get_token_balance(USDC, 6)
    pol_price_usd = float(POL_USD_PRICE)
    # Always use real on-chain balances (fixed 2026-05-01)
    total_value = usdt + usdc + (wmatic * current_price) + (pol * pol_price_usd)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "usdt": f"{usdt:.6f}",
        "usdc": f"{usdc:.6f}",
        "wmatic": f"{wmatic:.6f}",
        "pol": f"{pol:.6f}",
        "pol_usd_price": f"{pol_price_usd:.6f}",
        "total_value": f"{total_value:.6f}",
    }
    headers = _portfolio_history_header()
    write_header = True
    if os.path.exists(PORTFOLIO_HISTORY_FILE):
        try:
            with open(PORTFOLIO_HISTORY_FILE, "r", encoding="utf-8", newline="") as fh:
                first_line = (fh.readline() or "").strip()
                write_header = first_line != ",".join(headers)
        except Exception:
            write_header = True
    mode = "w" if write_header else "a"
    with open(PORTFOLIO_HISTORY_FILE, mode, encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


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
    take_profit_pct, strong_signal_tp = _effective_take_profit_thresholds()

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

    if gain_pct >= strong_signal_tp:
        return True, {
            "reason": "STRONG_TP_HIT",
            "message": (
                f"Strong TP hit | buy ${buy_price:.4f} -> now ${current_price:.4f} "
                f"({gain_pct:.2f}%) >= {strong_signal_tp:.2f}%"
            ),
            "sell_fraction": STRONG_TP_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    if gain_pct >= take_profit_pct:
        return True, {
            "reason": "TP_HIT",
            "message": (
                f"Take-profit hit | buy ${buy_price:.4f} -> now ${current_price:.4f} "
                f"({gain_pct:.2f}%) >= {take_profit_pct:.2f}%"
            ),
            "sell_fraction": TAKE_PROFIT_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    if peak_gain_pct >= take_profit_pct and pullback_pct >= TRAILING_STOP_PCT:
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
    _, strong_signal_tp = _effective_take_profit_thresholds()

    if reason == "PER_TRADE_EXIT" and open_trade:
        buy_price = float(open_trade["buy_price"])
        gain_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
        sell_fraction = STRONG_TP_SELL_PCT if gain_pct >= strong_signal_tp else TAKE_PROFIT_SELL_PCT
        message = (
            f"🛡️ PROTECTION EXIT: {'strong TP hit' if gain_pct >= strong_signal_tp else 'TP hit'} | "
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
        _log_trade_skipped(f"cooldown (all wallets in {PER_WALLET_COOLDOWN}s window)")
        return TradeDecision(message=f"TRADE SKIPPED: cooldown (all wallets in {PER_WALLET_COOLDOWN}s window)")

    trade_size = max(8.0, min(18.0, balances.usdt * COPY_TRADE_PCT))
    return TradeDecision(
        direction="USDT_TO_WMATIC",
        amount_in=int(trade_size * 1_000_000),
        trade_size=trade_size,
        message="🔄 REAL POLYCOPY MODE (20%) - Monitoring live wallets",
    )

def _strong_x_signal_buy_present() -> bool:
    """True if followed_equities has a BUY with strength ≥ X_SIGNAL_STRONG_THRESHOLD (same bar as equity trades)."""
    cfg = _load_followed_equities_json_dict()
    if not bool(cfg.get("enabled", True)):
        return False
    min_strength = _effective_equity_signal_min(cfg)
    strong_thr = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.80"))
    assets_seq = X_SIGNAL_EQUITY_TRADER.load_followed_equities()
    _, eligible = _sorted_and_eligible_equities(assets_seq, min_strength)
    return any(
        float(a.signal_strength) > 0 and float(a.signal_strength) >= strong_thr for a in eligible
    )


def ensure_usdc_for_x_signal(min_usdc: float = 8.0, min_wmatic_value: float = 15.0) -> bool:
    """If USDC is below ``min_usdc`` and a strong X-Signal BUY is active, swap WMATIC→USDC (preferred) or USDT→USDC."""
    balances = get_balances()
    if balances.usdc >= min_usdc:
        return True
    if not _strong_x_signal_buy_present():
        return False

    gst = GAS_PROTECTOR.get_safe_status(address=WALLET, urgent=False, min_pol=MIN_POL_FOR_GAS)
    if not gst.get("ok", False):
        print(f"{_nanolog()}AUTO-USDC skipped — gas/POL guard")
        return False

    key = os.getenv("POLYGON_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
    if not key:
        print(f"{_nanolog()}AUTO-USDC skipped — no private key")
        return False

    try:
        wmatic_price = float(get_live_wmatic_price())
    except Exception:
        wmatic_price = 0.0
    if wmatic_price <= 0:
        print(f"{_nanolog()}AUTO-USDC skipped — WMATIC price unavailable")
        return False

    shortfall = max(0.0, float(min_usdc) - float(balances.usdc))
    # Gas-optimized: if we need to populate, do a meaningful swap (avoid $0.40 USDC drips).
    target_usd = max(shortfall * 1.05, float(AUTO_POPULATE_USDC_AMOUNT))
    wmatic_usd = balances.wmatic * wmatic_price

    async def _swap_wmatic(amount_wei: int) -> bool:
        if amount_wei <= 0:
            return False
        h = await approve_and_swap(
            w3,
            key,
            amount_wei,
            direction="WMATIC_TO_USDC",
        )
        return h is not None

    async def _swap_usdt(amount_units: int) -> bool:
        if amount_units <= 0:
            return False
        h = await approve_and_swap(
            w3,
            key,
            amount_units,
            direction="USDT_TO_USDC",
        )
        return h is not None

    def _run(coro):
        return asyncio.run(coro)

    use_wmatic_first = wmatic_usd >= float(min_wmatic_value)
    if use_wmatic_first:
        swap_usd = min(wmatic_usd * 0.95, target_usd)
        wmatic_to_swap = min(balances.wmatic * 0.95, swap_usd / wmatic_price)
        amount_wei = int(wmatic_to_swap * 1e18)
        if amount_wei > 0:
            print(f"🔄 AUTO-USDC | Swapping ${swap_usd:.2f} from WMATIC → USDC (gas optimized)")
            ok = _run(_swap_wmatic(amount_wei))
            if ok:
                print(f"🔄 AUTO-USDC | Swapped ${swap_usd:.2f} from WMATIC → USDC (gas optimized)")
            if ok and get_balances().usdc >= min_usdc:
                return True
        after = get_balances()
        if after.usdt >= 0.5:
            print("🔄 AUTO-USDC | Using USDT path (fallback)")
            usdt_amt = min(after.usdt * 0.95, target_usd)
            ok2 = _run(_swap_usdt(int(usdt_amt * 1_000_000)))
            return ok2 and get_balances().usdc >= min_usdc
        return get_balances().usdc >= min_usdc

    print("🔄 AUTO-USDC | Using USDT path (fallback)")
    after = get_balances()
    usdt_amt = min(after.usdt * 0.95, target_usd)
    ok = _run(_swap_usdt(int(usdt_amt * 1_000_000)))
    return ok and get_balances().usdc >= min_usdc


def _project_balances_after_auto_usdc(
    balances: Balances,
    *,
    min_usdc: float,
    min_wmatic_value: float,
) -> Balances:
    """Mirror ``ensure_usdc_for_x_signal`` guards and sizing without swaps (dry-run fair USDC for equity plans)."""
    if balances.usdc >= min_usdc:
        return balances
    if not _strong_x_signal_buy_present():
        return balances

    gst = GAS_PROTECTOR.get_safe_status(address=WALLET, urgent=False, min_pol=MIN_POL_FOR_GAS)
    if not gst.get("ok", False):
        return balances

    key = os.getenv("POLYGON_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
    if not key:
        return balances

    try:
        wmatic_price = float(get_live_wmatic_price())
    except Exception:
        return balances
    if wmatic_price <= 0:
        return balances

    shortfall = max(0.0, float(min_usdc) - float(balances.usdc))
    target_usd = max(shortfall * 1.05, float(AUTO_POPULATE_USDC_AMOUNT))
    wmatic_usd = balances.wmatic * wmatic_price

    use_wmatic_first = wmatic_usd >= float(min_wmatic_value)
    if use_wmatic_first:
        swap_usd = min(wmatic_usd * 0.95, target_usd)
        wmatic_to_swap = min(balances.wmatic * 0.95, swap_usd / wmatic_price)
        if wmatic_to_swap > 0:
            est_usdc_out = min(wmatic_to_swap * wmatic_price, swap_usd)
            if balances.usdc + est_usdc_out >= min_usdc:
                return Balances(
                    usdt=balances.usdt,
                    wmatic=balances.wmatic - wmatic_to_swap,
                    pol=balances.pol,
                    usdc=balances.usdc + est_usdc_out,
                )
        if balances.usdt >= 0.5:
            usdt_amt = min(balances.usdt * 0.95, target_usd)
            if usdt_amt > 0 and balances.usdc + usdt_amt >= min_usdc:
                return Balances(
                    usdt=balances.usdt - usdt_amt,
                    wmatic=balances.wmatic,
                    pol=balances.pol,
                    usdc=balances.usdc + usdt_amt,
                )
        return balances

    if balances.usdt >= 0.5:
        usdt_amt = min(balances.usdt * 0.95, target_usd)
        if usdt_amt > 0 and balances.usdc + usdt_amt >= min_usdc:
            return Balances(
                usdt=balances.usdt - usdt_amt,
                wmatic=balances.wmatic,
                pol=balances.pol,
                usdc=balances.usdc + usdt_amt,
            )
    return balances


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


def try_x_signal_equity_decision(balances: Balances, *, dry_run: bool = False) -> Optional[TradeDecision]:
    """Highest-priority iteration: eligible assets × SignalEquityTrader.build_plan; first plan wins."""
    decision: Optional[TradeDecision] = None
    result: Optional[str] = None
    eligible_count = 0
    # Python if/else blocks do not create a new local scope; assignments below mutate this function-local flag.
    buy_paths_allowed = True
    buy_paths_block_reason = f"pol<{MIN_POL_FOR_GAS:.4f} and AUTO_TOPUP_POL=false"

    def _polygon_chain_hint(sym: str, token_address: str) -> Optional[str]:
        t = (token_address or "").strip().lower()
        eth_like = {
            "0xb812837b81a3a6b81d7cd74cfb19a7f2784555e5",
            "0xba47214edd2bb43099611b208f75e4b42fdcfedc",
            "0x2d1f7226bd1f780af6b9a49dcc0ae00e8df4bdee",
        }
        if t in eth_like:
            return f"{sym}: token may be wrong chain (not Polygon)"
        return None

    if not ENABLE_X_SIGNAL_EQUITY:
        print(
            f"X-SIGNAL EQUITY SUMMARY | Assets checked: {eligible_count} | USDC: ${balances.usdc:.2f} | "
            f"Result: {'NO_TRADE_ENABLE_X_SIGNAL_EQUITY_FALSE'}"
        )
        return None

    cfg = _load_followed_equities_json_dict()
    cfg_enabled = bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
    min_strength = _effective_equity_signal_min(cfg)
    print(
        f"{_nanolog()}X-Signal threshold (max(followed_equities.min_signal_strength, "
        f"env X_SIGNAL_EQUITY_MIN_STRENGTH)) = {min_strength:.4f}"
    )

    assets_seq = X_SIGNAL_EQUITY_TRADER.load_followed_equities()
    assets, eligible = _sorted_and_eligible_equities(assets_seq, min_strength)
    eligible_count = len(eligible)
    high_conviction = bool(cfg_enabled) and any(
        float(a.signal_strength) >= 0.88 for a in eligible if float(a.signal_strength) > 0
    )
    if high_conviction:
        print("🚀 HIGH-CONVICTION MODE ACTIVE — 0.80+ signal present, gas protection relaxed for this cycle")

    print(f"🟦 X-SIGNAL EQUITY CHECK | Checking {len(assets)} assets")
    if not cfg_enabled:
        result = f"NO TRADE | followed_equities disabled (enabled=false in {FOLLOWED_EQUITIES_PATH})"
        print(f"🟦 X-SIGNAL EQUITY | {result}")
    elif not assets:
        result = "NO TRADE | no assets loaded (missing file, bad JSON, or empty assets[])"
        print(f"🟦 X-SIGNAL EQUITY | {result}")
    elif not eligible:
        result = (
            f"NO TRADE | no_asset_above_threshold (need abs(signal)>={min_strength:.2f}; "
            f"raise signal or lower min_signal_strength/env X_SIGNAL_EQUITY_MIN_STRENGTH)"
        )
        print(
            f"🟦 X-SIGNAL EQUITY | No valid plan this cycle "
            f"(reason: no_asset_above_threshold (>={min_strength:.2f}))"
        )
    else:
        # === PnL+ SPRINT OVERRIDE (high-conviction bypass) ===
        if high_conviction:
            print(
                "🚀 HIGH-CONVICTION GAS OVERRIDE | 0.80+ strength detected — bypassing 450 gwei limit "
                "(PnL+ Sprint Mode, high return high conviction, net expected positive)"
            )
            # Force USDC top-up for high-conviction.
            if dry_run:
                balances = _project_balances_after_auto_usdc(
                    balances,
                    min_usdc=8.0,
                    min_wmatic_value=12.0,
                )
            else:
                topup_ok = ensure_usdc_for_x_signal(min_usdc=8.0, min_wmatic_value=12.0)
                balances = get_balances()
                if not topup_ok and balances.usdc < 8.0:
                    print(
                        "🟦 X-SIGNAL EQUITY | Auto-USDC failed during HIGH-CONVICTION prep "
                        "(PnL+ Sprint Mode, high return high conviction)"
                    )
                    _log_trade_skipped(
                        f"AUTO-USDC failed during high-conviction prep (have ${balances.usdc:.2f}, need $8.00)"
                    )

        strong_thr = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.80"))
        has_strong_buy = any(
            float(a.signal_strength) > 0 and float(a.signal_strength) >= strong_thr for a in eligible
        )
        trader = _tuned_signal_equity_trader(min_strength)
        min_trade_usdc = float(trader.config.min_trade_usdc)
        min_usdc = float(X_SIGNAL_USDC_MIN)
        required_usdc_floor = max(float(min_usdc), min_trade_usdc)
        # Align auto-USDC with equity sizing: never aim below min_trade_usdc.
        auto_usdc_target = required_usdc_floor

        force_floor = float(min_usdc)
        if has_strong_buy and balances.usdc < max(force_floor, auto_usdc_target):
            if dry_run:
                balances = _project_balances_after_auto_usdc(
                    balances,
                    min_usdc=max(force_floor, auto_usdc_target),
                    min_wmatic_value=float(X_SIGNAL_WMATIC_MIN_VALUE),
                )
            else:
                topup_ok = ensure_usdc_for_x_signal(
                    min_usdc=max(force_floor, auto_usdc_target),
                    min_wmatic_value=float(X_SIGNAL_WMATIC_MIN_VALUE),
                )
                balances = get_balances()
                if not topup_ok and balances.usdc < max(force_floor, min_trade_usdc):
                    print(
                        "🟦 X-SIGNAL EQUITY | Auto-USDC attempt failed "
                        "(guard/tx) — BUY paths may be skipped"
                    )
                    _log_trade_skipped(
                        f"AUTO-USDC failed (have ${balances.usdc:.2f}, need ${max(force_floor, min_trade_usdc):.2f})"
                    )
            if balances.usdc >= max(force_floor, min_trade_usdc):
                if dry_run:
                    print(
                        "🟦 X-SIGNAL EQUITY | DRY-RUN: projected post auto-USDC | Proceeding with BUY analysis"
                    )
                else:
                    print("🟦 X-SIGNAL EQUITY | USDC ensured via WMATIC/USDT | Proceeding with BUY")
            else:
                print(
                    f"🟦 X-SIGNAL EQUITY | Auto-USDC insufficient for BUY equity "
                    f"(USDC ${balances.usdc:.2f} < ${max(force_floor, min_trade_usdc):.2f}) — BUY paths skipped"
                )
                _log_trade_skipped(
                    f"USDC low (have ${balances.usdc:.2f}, need ${max(force_floor, min_trade_usdc):.2f})"
                )

        if not dry_run and has_strong_buy:
            balances = get_balances()
            if float(balances.pol) < float(MIN_POL_FOR_GAS):
                if AUTO_TOPUP_POL:
                    if ensure_pol_for_trade(min_pol=float(MIN_POL_FOR_GAS)):
                        balances = get_balances()
                        if float(balances.pol) >= float(MIN_POL_FOR_GAS):
                            # Recover BUY paths if a prior top-up attempt failed but this one succeeds.
                            buy_paths_allowed = True
                            buy_paths_block_reason = (
                                f"pol recovered to >= {MIN_POL_FOR_GAS:.4f} after AUTO_TOPUP_POL=true retry"
                            )
                        else:
                            print(
                                f"{_nanolog()}AUTO-POL reported success but POL still low "
                                f"(pol≈{float(balances.pol):.4f} < {MIN_POL_FOR_GAS:.4f}) — BUY paths skipped"
                            )
                            buy_paths_allowed = False
                            buy_paths_block_reason = (
                                f"pol<{MIN_POL_FOR_GAS:.4f} after AUTO_TOPUP_POL=true success response"
                            )
                            _log_trade_skipped(
                                f"POL low for BUY path after top-up (pol={float(balances.pol):.4f}, min={MIN_POL_FOR_GAS:.4f})"
                            )
                    else:
                        print(
                            f"{_nanolog()}AUTO-POL failed during X-SIGNAL prep "
                            f"(pol<{MIN_POL_FOR_GAS:.4f}) — BUY paths skipped"
                        )
                        buy_paths_allowed = False
                        buy_paths_block_reason = (
                            f"pol<{MIN_POL_FOR_GAS:.4f} and AUTO_TOPUP_POL=true (auto-topup failed)"
                        )
                else:
                    print(
                        f"{_nanolog()}POL low (pol≈{float(balances.pol):.4f} < {MIN_POL_FOR_GAS:.4f}) "
                        f"and AUTO_TOPUP_POL=false — BUY paths skipped"
                    )
                    buy_paths_allowed = False
                    buy_paths_block_reason = f"pol<{MIN_POL_FOR_GAS:.4f} and AUTO_TOPUP_POL=false"
                    _log_trade_skipped(
                        f"POL low for BUY path (pol={float(balances.pol):.4f}, min={MIN_POL_FOR_GAS:.4f})"
                    )

        reason_parts: list[str] = []
        chain_notes: list[str] = []

        for a in eligible:
            hint = _polygon_chain_hint(str(a.symbol), str(a.token_address))
            if hint:
                chain_notes.append(hint)

        for a in eligible:
            sym = str(a.symbol).strip()
            sig = float(a.signal_strength)
            action_label = "BUY" if sig > 0 else "SELL"
            print(
                f"🟦 X-SIGNAL EQUITY ACTIVE | {sym} | Strength {sig:.3f} | Action: {action_label}"
            )
            if sig > 0 and not buy_paths_allowed:
                reason_parts.append(f"{sym}: buy_skipped ({buy_paths_block_reason})")
                _log_trade_skipped(f"POL low ({sym} buy blocked)")
                continue
            if sig >= 0.80:
                print(f"🚀 HIGH-CONVICTION BYPASS | Strength {sig:.2f} — forcing trade even on high gas/low USDC (PnL+ Sprint Mode)")
            if sig > 0 and balances.usdc < required_usdc_floor:
                reason_parts.append(
                    f"{sym}: buy_skipped (USDC ${balances.usdc:.2f} < required_floor ${required_usdc_floor:.2f}; "
                    f"min_trade_usdc ${min_trade_usdc:.2f})"
                )
                _log_trade_skipped(
                    f"USDC low ({sym} buy blocked: ${balances.usdc:.2f} < ${required_usdc_floor:.2f})"
                )
                continue
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
                allow_high_gas_override=high_conviction,
            )
            if plan:
                dynamic_trade_size_usdc = float(plan.trade_size)
                if str(plan.direction) == "USDC_TO_EQUITY":
                    strength = abs(sig)
                    # Dynamic sizing based on signal strength (Tier 1 - 2026-05-01)
                    if strength >= 0.90:
                        trade_size_usdc = 12.0
                    elif strength >= 0.80:
                        trade_size_usdc = 10.0
                    else:
                        trade_size_usdc = 8.0
                    desired_trade_size_usdc = float(trade_size_usdc)
                    available_usdc = float(balances.usdc)
                    # Safety: never request more USDC than wallet balance.
                    dynamic_trade_size_usdc = min(desired_trade_size_usdc, available_usdc)
                    if dynamic_trade_size_usdc < min_trade_usdc:
                        reason_parts.append(
                            f"{sym}: buy_skipped (dynamic_size ${desired_trade_size_usdc:.2f}, "
                            f"available_usdc ${available_usdc:.2f}, min_trade_usdc ${min_trade_usdc:.2f})"
                        )
                        _log_trade_skipped(
                            f"USDC low ({sym} dynamic size capped below min trade: ${dynamic_trade_size_usdc:.2f})"
                        )
                        continue
                _checksum = getattr(Web3, "to_checksum_address", lambda x: x)
                tin_p = _checksum(str(plan.token_in).strip())
                tout_p = _checksum(str(plan.token_out).strip())
                print(
                    f"{_nanolog()}X-Signal swap intent | {plan.direction} | "
                    f"{sym} | token_in={tin_p} token_out={tout_p}"
                )
                secs = int(trader.config.per_asset_cooldown_seconds)
                decision = TradeDecision(
                    direction=plan.direction,
                    amount_in=(
                        int(dynamic_trade_size_usdc * 1_000_000)
                        if str(plan.direction) == "USDC_TO_EQUITY"
                        else plan.amount_in
                    ),
                    trade_size=dynamic_trade_size_usdc,
                    message=plan.message,
                    token_in=plan.token_in,
                    token_out=plan.token_out,
                    cooldown_asset=(sym, secs),
                )
                result = decision.message or (decision.direction or "TRADE")
                break
            hints: list[str] = []
            if balances.usdc <= 0 and sig > 0:
                hints.append("zero_usdc_for_buy_path")
            if equity_bal <= 0 and sig < 0:
                hints.append("zero_equity_balance_for_sell_path")
            gst_early = trader.gas_protector.get_safe_status(
                address=WALLET, urgent=False, min_pol=float(trader.config.min_pol_for_gas)
            )
            gas_ok_early = bool(gst_early.get("gas_ok", False))
            fresh_pol_early = float(gst_early.get("pol_balance", 0.0) or 0.0)
            pol_ok_early = fresh_pol_early >= float(trader.config.min_pol_for_gas)
            if not gas_ok_early:
                hints.append(
                    f"gas_guard_blocked (gas {float(gst_early.get('gas_gwei', 0.0)):.2f} > "
                    f"{float(gst_early.get('max_gwei', 0.0)):.2f} gwei)"
                )
            if not pol_ok_early:
                hints.append(
                    f"pol_guard_blocked (pol {fresh_pol_early:.4f} < "
                    f"{float(trader.config.min_pol_for_gas):.4f})"
                )
            if not can_trade_asset(
                sym,
                now=None,
                cooldown_seconds=int(trader.config.per_asset_cooldown_seconds),
            ):
                hints.append(f"per_asset_cooldown={trader.config.per_asset_cooldown_seconds}s")
                _log_trade_skipped(f"cooldown ({sym}: {trader.config.per_asset_cooldown_seconds}s)")
            min_usdc_trade = float(trader.config.min_trade_usdc)
            if not hints and gas_ok_early and pol_ok_early:
                if sig > 0 and balances.usdc >= min_usdc_trade:
                    hints.append(
                        "build_plan_returned_none (BUY: earnings_window/strong_threshold_internal/risk_filters)"
                    )
                elif sig < 0 and equity_bal > 0:
                    hints.append(
                        "build_plan_returned_none (SELL: earnings_window/dust_below_min_units/risk_filters)"
                    )
                elif sig > 0 and 0 < balances.usdc < min_usdc_trade:
                    hints.append(
                        f"below_min_trade_usdc (have ${balances.usdc:.2f}, need≥${min_usdc_trade:.2f})"
                    )
            if not hints:
                hints.append(f"risk_filters_or_router_none_for_{sym}")
            reason_parts.append(f"{sym}: " + "; ".join(dict.fromkeys(hints)))

        if not decision:
            summary_bits: list[str] = []
            if chain_notes:
                summary_bits.append("chain: " + " | ".join(chain_notes[:2]))
            if balances.usdc < float(trader.config.min_trade_usdc) and any(
                float(x.signal_strength) > 0 for x in eligible
            ):
                summary_bits.append(
                    f"usdc=${balances.usdc:.2f} < min_trade_usdc={trader.config.min_trade_usdc:.2f} (cannot size BUY)"
                )
            gst = trader.gas_protector.get_safe_status(
                address=WALLET, urgent=False, min_pol=float(trader.config.min_pol_for_gas)
            )
            if high_conviction:
                summary_bits.append(
                    "gas override active (0.80+ high conviction; bypassing max_gwei block)"
                )
            elif not bool(gst.get("gas_ok", False)):
                summary_bits.append(
                    f"gas blocked (gas≈{float(gst.get('gas_gwei', 0)):.2f}, "
                    f"limit≤{float(gst.get('max_gwei', 0)):.2f})"
                )
            else:
                summary_bits.append("gas_ok")
            fresh_pol = float(gst.get("pol_balance", 0.0) or 0.0)
            if fresh_pol < float(trader.config.min_pol_for_gas):
                summary_bits.append(
                    f"POL blocked (pol≈{fresh_pol:.4f}, "
                    f"need≥{float(trader.config.min_pol_for_gas):.4f})"
                )
            merged = (
                " | ".join(reason_parts[:4])
                + (f" …(+{len(reason_parts)-4} more symbols)" if len(reason_parts) > 4 else "")
            )
            if summary_bits:
                print(
                    "🟦 X-SIGNAL EQUITY NO PLAN — "
                    + " | ".join(summary_bits)
                    + (" | detail: " + merged if merged else "")
                )
            else:
                print(f"🟦 X-SIGNAL EQUITY | No valid plan this cycle (reason: {merged})")

            compact = "; ".join(summary_bits) + (" — " + merged if merged else "")
            result = (compact[:500] + "…") if len(compact) > 500 else compact if compact else merged

        if ENABLE_X_SIGNAL_EQUITY and decision is None and eligible and cfg_enabled:
            if not result:
                result = "NO TRADE"

    print(f"X-SIGNAL EQUITY SUMMARY | Assets checked: {eligible_count} | USDC: ${balances.usdc:.2f} | Result: {result or 'NO TRADE'}")

    return decision


def evaluate_x_signal_equity_trade(
    balances: Balances,
    *,
    trader: SignalEquityTrader = X_SIGNAL_EQUITY_TRADER,
) -> Optional[EquityTradePlan]:
    """Same eligibility + sorting as `try_x_signal_equity_decision` without diagnostic prints."""
    if not ENABLE_X_SIGNAL_EQUITY:
        return None
    cfg = _load_followed_equities_json_dict()
    cfg_enabled = bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
    if not cfg_enabled:
        return None
    min_strength = _effective_equity_signal_min(cfg)
    assets_seq = trader.load_followed_equities()
    _, eligible = _sorted_and_eligible_equities(assets_seq, min_strength)
    if not eligible:
        return None
    tuned = _tuned_signal_equity_trader(min_strength)
    for a in eligible:
        equity_balance = get_token_balance(a.token_address, int(a.decimals))
        sym = str(a.symbol).strip()
        plan = tuned.build_plan(
            symbol=sym,
            token_address=str(a.token_address).strip(),
            token_decimals=int(a.decimals),
            signal_strength=float(a.signal_strength),
            earnings_proximity_days=a.earnings_days,
            current_price_usd=a.current_price_usd,
            usdc_balance=balances.usdc,
            equity_balance=equity_balance,
            wallet_address_for_gas=WALLET,
            can_trade_asset=can_trade_asset,
        )
        if plan:
            return plan
    return None


async def evaluate_usdc_copy_trade(
    balances: Balances,
    wallets: list[str],
    *,
    strategy: Optional[USDCopyStrategy] = None,
) -> TradeDecision:
    if not ENABLE_USDC_COPY:
        return TradeDecision(message="ℹ️ USDC copy disabled")

    usdc_strategy = strategy if strategy is not None else USDC_COPY_STRATEGY
    plan = usdc_strategy.build_plan(
        usdc_balance=balances.usdc,
        wallets=wallets,
        wallet_address_for_gas=WALLET,
        can_trade_wallet=can_trade_wallet,
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


def determine_trade_decision(
    state: dict,
    balances: Balances,
    current_price: float,
    *,
    dry_run: bool = False,
) -> TradeDecision:
    print(
        f"\n{_nanolog()}=== CYCLE {int(time.time())} | BALANCES: USDT=${balances.usdt:.2f} "
        f"USDC=${balances.usdc:.2f} WMATIC=${balances.wmatic:.2f} ==="
    )
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
    print(
        f"{_nanolog()}Runtime config | TAKE_PROFIT_PCT={TAKE_PROFIT_PCT:.2f} "
        f"STRONG_SIGNAL_TP={STRONG_SIGNAL_TP:.2f} "
        f"PER_ASSET_COOLDOWN_MINUTES={PER_ASSET_COOLDOWN_MINUTES}"
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
        xd = try_x_signal_equity_decision(balances, dry_run=dry_run)
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
            )
            if plan:
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
        current_price = get_live_wmatic_price()
        write_portfolio_history_snapshot(current_price)

        if is_global_cooldown_active(state):
            lr = float(state.get("last_run") or 0.0)
            elapsed_s = max(0.0, time.time() - lr)
            remain_s = max(0.0, COOLDOWN_MINUTES * 60 - elapsed_s)
            print(
                f"{_nanolog()}skip cycle — global cooldown ~{remain_s:.0f}s left "
                f"(COOLDOWN_MINUTES={COOLDOWN_MINUTES}; last_run was {elapsed_s:.0f}s ago)"
            )
            _log_trade_skipped(f"cooldown (global, ~{remain_s:.0f}s left)")
            return

        decision = await asyncio.to_thread(
            lambda: determine_trade_decision(state, balances, current_price, dry_run=dry_run)
        )
        save_state(state)

        if decision.message:
            print(decision.message)

        if not decision.should_execute:
            _log_trade_skipped("protection/strategy returned no actionable trade")
            print("ℹ️ No actionable trade this cycle")
            return

        if dry_run:
            print(f"🧪 DRY RUN: would execute {decision.direction} for amount_in={decision.amount_in}")
            return

        pol_now = float(get_pol_balance())
        if pol_now < float(MIN_POL_FOR_GAS):
            if AUTO_TOPUP_POL:
                # Run sync top-up off the active event loop (ensure_pol_for_trade uses asyncio.run internally).
                topup_ok = await asyncio.to_thread(
                    ensure_pol_for_trade,
                    float(MIN_POL_FOR_GAS),
                )
                if not topup_ok:
                    _log_trade_skipped(f"POL low (auto top-up failed; need {MIN_POL_FOR_GAS:.4f})")
                    print(f"{_nanolog()}AUTO-POL failed — trade blocked (pol<{MIN_POL_FOR_GAS:.3f})")
                    return
            else:
                _log_trade_skipped(f"POL low (have {pol_now:.4f}, need {MIN_POL_FOR_GAS:.4f})")
                print(
                    f"{_nanolog()}POL low (pol≈{pol_now:.4f} < {MIN_POL_FOR_GAS:.4f}) and AUTO_TOPUP_POL=false — trade blocked"
                )
                return

        gas_status = get_gas_status()
        if not gas_status["ok"]:
            gas_gwei = float(gas_status.get("gas_gwei") or 0.0)
            if gas_gwei <= 400.0:
                print("⚠️ High gas but forcing trade (urgent mode)")
            else:
                _log_trade_skipped(
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
            os.getenv("POLYGON_PRIVATE_KEY") or os.getenv("PRIVATE_KEY"),
            decision.amount_in,
            direction=decision.direction,
            token_in=decision.token_in,
            token_out=decision.token_out,
        )
        if tx_hash:
            print("✅ Swap executed successfully!")
            if decision.cooldown_asset:
                sym_ca, secs_a = decision.cooldown_asset
                mark_asset_traded(sym_ca, cooldown_seconds=int(secs_a))
            if decision.cooldown_wallet and decision.cooldown_wallet[0]:
                wal_cw, secs_w = decision.cooldown_wallet
                mark_wallet_traded(str(wal_cw).strip(), cooldown_seconds=int(secs_w))
        else:
            print(f"{_nanolog()}Swap failed — per-asset/per-wallet cooldown not applied")

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