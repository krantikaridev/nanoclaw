"""Runtime: env, singletons, balances, state, take-profit, POL helpers.

Modular extraction from ``clean_swap`` (krantikaridev/nanoclaw V2).
"""
import asyncio
import csv
import importlib
import json
import logging
import os
import time
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv

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

load_dotenv()
# Optional local override file (kept for VM/operator compatibility).
load_dotenv(".env.local", override=True)


from constants import ERC20_ABI, LOG_PREFIX, USDC, USDT, WALLET, WMATIC  # noqa: E402
from nanoclaw.config import default_json_rpc_url  # noqa: E402
from nanoclaw.utils.gas_protector import GasProtector  # noqa: E402
from nanoclaw.strategies.usdc_copy import USDCopyStrategy  # noqa: E402
from nanoclaw.strategies.signal_equity_trader import (  # noqa: E402
    SignalEquityTrader,
    FollowedEquity,
)
from swap_executor import approve_and_swap  # noqa: E402

logger = logging.getLogger(__name__)

LOCK_FILE = os.path.join(tempfile.gettempdir(), "nanoclaw.lock")
STATE_FILE = "bot_state.json"
TRADE_LOG_FILE = "trade_exits.json"
PORTFOLIO_HISTORY_FILE = "portfolio_history.csv"

COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 3))
PER_ASSET_COOLDOWN_MINUTES = int(os.getenv("PER_ASSET_COOLDOWN_MINUTES", "30"))
PER_ASSET_COOLDOWN_SECONDS = PER_ASSET_COOLDOWN_MINUTES * 60
POL_USD_PRICE = float(os.getenv("POL_USD_PRICE", "0.10"))
MIN_POL_FOR_GAS = float(os.getenv("MIN_POL_FOR_GAS", "0.005"))
AUTO_TOPUP_POL = os.getenv("AUTO_TOPUP_POL", "true").lower() == "true"
POL_TOPUP_AMOUNT = float(os.getenv("POL_TOPUP_AMOUNT", "0.03"))
COPY_TRADE_PCT = float(os.getenv("COPY_TRADE_PCT", "0.28"))
PER_WALLET_COOLDOWN = int(os.getenv("PER_WALLET_COOLDOWN", "180"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "5.0"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
STRONG_SIGNAL_TP = float(os.getenv("STRONG_SIGNAL_TP", "12.0"))
TAKE_PROFIT_SELL_PCT = float(os.getenv("TAKE_PROFIT_SELL_PCT", "0.45"))
STRONG_TP_SELL_PCT = float(os.getenv("STRONG_TP_SELL_PCT", "0.60"))
ENABLE_USDC_COPY = os.getenv("ENABLE_USDC_COPY", "false").lower() == "true"
ENABLE_X_SIGNAL_EQUITY = os.getenv("ENABLE_X_SIGNAL_EQUITY", "false").lower() == "true"
X_SIGNAL_EQUITY_MIN_STRENGTH = float(os.getenv("X_SIGNAL_EQUITY_MIN_STRENGTH", "0.60"))
X_SIGNAL_MAX_EARNINGS_DAYS = float(os.getenv("X_SIGNAL_MAX_EARNINGS_DAYS", "5.0"))
X_SIGNAL_FORCE_HIGH_CONVICTION = os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION", "true").lower() == "true"
X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = float(os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.82"))
X_SIGNAL_STRONG_THRESHOLD = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.82"))
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = float(
    os.getenv(
        "X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD",
        os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD", "0.82"),
    )
)
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC = float(os.getenv("X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC", "8.0"))
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC = float(os.getenv("X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC", "12.0"))
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


def _nanolog() -> str:
    p = (LOG_PREFIX or "").strip()
    return f"{p} " if p else ""


def _tp_thresholds_core() -> tuple[float, float]:
    """Read tier thresholds from ``clean_swap`` so tests can monkeypatch knobs."""
    cs = importlib.import_module("clean_swap")
    base_tp = float(cs.TAKE_PROFIT_PCT)
    strong_tp = float(cs.STRONG_SIGNAL_TP)
    if strong_tp <= base_tp:
        strong_tp = base_tp + 4.0
    return base_tp, strong_tp


def _effective_take_profit_thresholds() -> tuple[float, float]:
    """Default thresholds; façade layer may delegate via ``clean_swap._effective_take_profit_thresholds``."""
    return _tp_thresholds_core()


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


def _effective_floor_for_equity(asset: FollowedEquity, min_strength: float) -> float:
    asset_floor_raw = getattr(asset, "min_signal_strength", None)
    return float(min_strength) if asset_floor_raw is None else float(asset_floor_raw)



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
    return Web3(Web3.HTTPProvider(rpc_url or default_json_rpc_url()))


def build_gas_protector() -> GasProtector:
    return (
        GasProtector.builder()
        .with_max_gwei(float(os.getenv("MAX_GWEI", "80")))
        .with_urgent_gwei(float(os.getenv("URGENT_GWEI", "120")))
        .with_min_pol_balance(MIN_POL_FOR_GAS)
        .with_primary_rpc(default_json_rpc_url())
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
    .with_strong_signal_threshold(X_SIGNAL_STRONG_THRESHOLD)
    .with_max_earnings_days(float(os.getenv("X_SIGNAL_MAX_EARNINGS_DAYS", "5.0")))
    .with_min_signal_strength(float(os.getenv("X_SIGNAL_EQUITY_MIN_STRENGTH", "0.60")))
    .with_force_high_conviction(X_SIGNAL_FORCE_HIGH_CONVICTION)
    .with_high_conviction_threshold(X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD)
    .with_force_eligible_threshold(X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD)
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
    import importlib

    cs = importlib.import_module("clean_swap")
    wallet_address = cs.WALLET
    hist_path = str(cs.PORTFOLIO_HISTORY_FILE)
    pol_price_usd = float(cs.POL_USD_PRICE)

    usdt = cs.get_token_balance(cs.USDT, 6, wallet_address=wallet_address)
    wmatic = cs.get_token_balance(cs.WMATIC, 18, wallet_address=wallet_address)
    pol = cs.get_pol_balance(wallet_address=wallet_address)
    usdc = cs.get_token_balance(cs.USDC, 6, wallet_address=wallet_address)

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
    if os.path.exists(hist_path):
        try:
            with open(hist_path, "r", encoding="utf-8", newline="") as fh:
                first_line = (fh.readline() or "").strip()
                write_header = first_line != ",".join(headers)
        except Exception:
            write_header = True
    mode = "w" if write_header else "a"
    with open(hist_path, mode, encoding="utf-8", newline="") as fh:
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


def _get_latest_open_trade_core(trade_log_file: str = TRADE_LOG_FILE) -> Optional[dict]:
    if not os.path.exists(trade_log_file):
        return None

    try:
        with open(trade_log_file, "r", encoding="utf-8") as file_handle:
            trades = json.load(file_handle)
    except Exception:
        return None

    open_trades = [trade for trade in trades if trade.get("status") == "OPEN" and trade.get("buy_price")]
    return open_trades[-1] if open_trades else None


# Aliased on ``clean_swap`` for monkeypatch tests.
get_latest_open_trade = _get_latest_open_trade_core


def evaluate_take_profit(current_price: float, state: dict) -> Tuple[bool, Optional[dict]]:
    cs = importlib.import_module("clean_swap")
    trade = cs.get_latest_open_trade()
    tracking = state.setdefault("profit_tracking", {})
    take_profit_pct, strong_signal_tp = cs._effective_take_profit_thresholds()

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
            "sell_fraction": cs.STRONG_TP_SELL_PCT,
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
            "sell_fraction": cs.TAKE_PROFIT_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    if peak_gain_pct >= take_profit_pct and pullback_pct >= cs.TRAILING_STOP_PCT:
        return True, {
            "reason": "TRAILING_STOP_HIT",
            "message": (
                f"Trailing stop hit | peak ${peak_price:.4f} ({peak_gain_pct:.2f}%) -> "
                f"now ${current_price:.4f} ({pullback_pct:.2f}% off peak)"
            ),
            "sell_fraction": cs.TAKE_PROFIT_SELL_PCT,
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
    cs = importlib.import_module("clean_swap")
    sell_fraction = 0.45
    _, strong_signal_tp = cs._effective_take_profit_thresholds()

    if reason == "PER_TRADE_EXIT" and open_trade:
        buy_price = float(open_trade["buy_price"])
        gain_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
        sell_fraction = (
            cs.STRONG_TP_SELL_PCT if gain_pct >= strong_signal_tp else cs.TAKE_PROFIT_SELL_PCT
        )
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
