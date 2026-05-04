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

import config as cfg

from constants import ERC20_ABI, LOG_PREFIX, ROUTER, USDC, USDC_NATIVE, USDT, WALLET, WMATIC  # noqa: E402
from nanoclaw.config import connect_web3  # noqa: E402
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

# Runtime config aliases from central config.
COOLDOWN_MINUTES = cfg.COOLDOWN_MINUTES
PER_ASSET_COOLDOWN_MINUTES = cfg.PER_ASSET_COOLDOWN_MINUTES
PER_ASSET_COOLDOWN_SECONDS = cfg.PER_ASSET_COOLDOWN_SECONDS
POL_USD_PRICE = cfg.POL_USD_PRICE
MIN_POL_FOR_GAS = cfg.MIN_POL_FOR_GAS
AUTO_TOPUP_POL = cfg.AUTO_TOPUP_POL
POL_TOPUP_AMOUNT = cfg.POL_TOPUP_AMOUNT
COPY_TRADE_PCT = cfg.COPY_TRADE_PCT
MAX_GWEI = cfg.MAX_GWEI
FIXED_TRADE_USD_MIN = cfg.FIXED_TRADE_USD_MIN
FIXED_TRADE_USD_MAX = cfg.FIXED_TRADE_USD_MAX
PER_WALLET_COOLDOWN = cfg.PER_WALLET_COOLDOWN
TRAILING_STOP_PCT = cfg.TRAILING_STOP_PCT
TAKE_PROFIT_PCT = cfg.TAKE_PROFIT_PCT
STRONG_SIGNAL_TP = cfg.STRONG_SIGNAL_TP
TAKE_PROFIT_SELL_PCT = cfg.TAKE_PROFIT_SELL_PCT
STRONG_TP_SELL_PCT = cfg.STRONG_TP_SELL_PCT
ENABLE_USDC_COPY = cfg.ENABLE_USDC_COPY
ENABLE_X_SIGNAL_EQUITY = cfg.ENABLE_X_SIGNAL_EQUITY
X_SIGNAL_EQUITY_MIN_STRENGTH = cfg.X_SIGNAL_EQUITY_MIN_STRENGTH
X_SIGNAL_MAX_EARNINGS_DAYS = cfg.X_SIGNAL_MAX_EARNINGS_DAYS
X_SIGNAL_FORCE_HIGH_CONVICTION = cfg.X_SIGNAL_FORCE_HIGH_CONVICTION
X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = cfg.X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD
X_SIGNAL_STRONG_THRESHOLD = cfg.X_SIGNAL_STRONG_THRESHOLD
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = cfg.X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC = cfg.X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC = cfg.X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC
FOLLOWED_EQUITIES_PATH = cfg.FOLLOWED_EQUITIES_PATH
X_SIGNAL_USDC_MIN = cfg.X_SIGNAL_USDC_MIN
X_SIGNAL_WMATIC_MIN_VALUE = cfg.X_SIGNAL_WMATIC_MIN_VALUE
AUTO_POPULATE_USDC_AMOUNT = cfg.AUTO_POPULATE_USDC_AMOUNT
AUTO_USDC_FOR_X_SIGNAL_MIN_USDC = cfg.AUTO_USDC_FOR_X_SIGNAL_MIN_USDC
AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE = cfg.AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE
X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT = cfg.X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT
X_SIGNAL_USDC_SAFE_FLOOR = cfg.X_SIGNAL_USDC_SAFE_FLOOR
X_SIGNAL_AUTO_USDC_TARGET = cfg.X_SIGNAL_AUTO_USDC_TARGET


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
    # Mark-to-USDT (router quote) for followed equity tokens (WETH/LINK/...) not in core balances; bug fix 2026-05-03
    followed_equity_usd: float = 0.0
    # usdt+usdc+WMATIC*px+POL*px+followed_equity_usd; for dashboard / nanomon when liquid stables are 0 but positions exist
    total_portfolio_usd: float = 0.0


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
    return connect_web3(explicit_rpc=rpc_url)


def build_gas_protector() -> GasProtector:
    return (
        GasProtector.builder()
        .with_max_gwei(MAX_GWEI)
        .with_urgent_gwei(cfg.URGENT_GWEI)
        .with_min_pol_balance(MIN_POL_FOR_GAS)
        .with_retry_attempts(cfg.GAS_RPC_RETRY_ATTEMPTS)
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
    .with_max_earnings_days(X_SIGNAL_MAX_EARNINGS_DAYS)
    .with_min_signal_strength(X_SIGNAL_EQUITY_MIN_STRENGTH)
    .with_force_high_conviction(X_SIGNAL_FORCE_HIGH_CONVICTION)
    .with_high_conviction_threshold(X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD)
    .with_force_eligible_threshold(X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD)
    .with_per_asset_cooldown_seconds(PER_ASSET_COOLDOWN_SECONDS)
    .with_usdc_address(USDC)
    .with_gas_protector(GAS_PROTECTOR)
    .build()
)


def is_copy_trading_enabled() -> bool:
    return cfg.COPY_TRADING_ENABLED


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
        from web3 import Web3 as Web3Checksum

        token_a = Web3Checksum.to_checksum_address(str(token_address).strip())
        wallet_a = Web3Checksum.to_checksum_address(str(wallet_address).strip())
    except Exception:
        token_a = str(token_address).strip()
        wallet_a = str(wallet_address).strip()
    try:
        contract = client.eth.contract(address=token_a, abi=ERC20_ABI)
        return contract.functions.balanceOf(wallet_a).call() / (10**decimals)
    except Exception:
        return 0.0


def _total_usdc_balance(
    web3_client: Optional[Web3] = None,
    wallet_address: str = WALLET,
) -> float:
    """USDC.e (``USDC``) plus native Polygon USDC when it is a distinct contract."""
    total = get_token_balance(USDC, 6, web3_client=web3_client, wallet_address=wallet_address)
    native = (USDC_NATIVE or "").strip()
    if native and native.lower() != str(USDC).strip().lower():
        total += get_token_balance(native, 6, web3_client=web3_client, wallet_address=wallet_address)
    return total


def get_pol_balance(
    protector: GasProtector = GAS_PROTECTOR,
    wallet_address: str = WALLET,
) -> float:
    return protector.get_pol_balance(wallet_address)


def ensure_pol_for_trade(min_pol: float = 0.025) -> bool:
    current_pol = float(get_pol_balance())
    if current_pol >= float(min_pol):
        return True

    key = cfg.get_resolved_key()
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


def fixed_copy_trade_usd(usdc: float, usdt: float, copy_trade_pct: float) -> float:
    # FIXED SIZING: band per signal — bounds from FIXED_TRADE_USD_MIN / FIXED_TRADE_USD_MAX (.env).
    stable = max(0.0, float(usdc)) + max(0.0, float(usdt))
    raw = stable * float(copy_trade_pct)
    lo, hi = FIXED_TRADE_USD_MIN, FIXED_TRADE_USD_MAX
    if hi < lo:
        lo, hi = hi, lo
    return max(lo, min(hi, float(raw)))


def _followed_equity_tokens_usdt_usd() -> float:
    """Router-quoted USDT value for non-core followed tokens (excludes USDC/USDT/WMATIC already in Balances)."""
    from web3 import Web3

    from swap_executor import _best_quote_path, build_polygon_swap_path_candidates

    total = 0.0
    try:
        assets = X_SIGNAL_EQUITY_TRADER.load_followed_equities()
    except Exception:
        return 0.0
    for a in assets:
        addr = (a.token_address or "").strip()
        if not addr:
            continue
        al = addr.lower()
        core_tokens = {USDC.lower(), USDT.lower(), WMATIC.lower()}
        native = (USDC_NATIVE or "").strip().lower()
        if native:
            core_tokens.add(native)
        if al in core_tokens:
            continue
        bal = get_token_balance(addr, int(a.decimals))
        if bal <= 0:
            continue
        amt = int(bal * (10 ** int(a.decimals)))
        if amt <= 0:
            continue
        try:
            paths = build_polygon_swap_path_candidates(
                Web3.to_checksum_address(addr),
                Web3.to_checksum_address(USDT),
            )
            _, best_amt, _ = _best_quote_path(w3, router=ROUTER, amount_in=amt, paths=paths)
            total += best_amt / 1_000_000
        except Exception:
            continue
    return total


def get_balances() -> Balances:
    from protection import get_live_wmatic_price

    usdt = get_token_balance(USDT, 6)
    wmatic = get_token_balance(WMATIC, 18)
    pol = get_pol_balance()
    usdc = _total_usdc_balance()
    fe_usd = _followed_equity_tokens_usdt_usd()
    try:
        wmatic_px = float(get_live_wmatic_price())
    except Exception:
        wmatic_px = 0.0
    pol_price_usd = float(POL_USD_PRICE)
    total_pf = usdt + usdc + (wmatic * wmatic_px) + (pol * pol_price_usd) + fe_usd
    return Balances(
        usdt=usdt,
        wmatic=wmatic,
        pol=pol,
        usdc=usdc,
        followed_equity_usd=fe_usd,
        total_portfolio_usd=total_pf,
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
    # Use façade get_token_balance so tests monkeypatching ``clean_swap.get_token_balance`` stay consistent.
    usdc_addr = str(getattr(cs, "USDC", USDC)).strip()
    usdc = cs.get_token_balance(usdc_addr, 6, wallet_address=wallet_address)
    if USDC_NATIVE and USDC_NATIVE.lower() != usdc_addr.lower():
        usdc += cs.get_token_balance(USDC_NATIVE, 6, wallet_address=wallet_address)

    # Deployed equity tokens (WETH/LINK/…) quoted via router — keeps CSV aligned with nanomon when stables are drained.
    fe_usd = _followed_equity_tokens_usdt_usd()
    total_value = usdt + usdc + (wmatic * current_price) + (pol * pol_price_usd) + fe_usd
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
    prot = importlib.import_module("protection")
    sell_fraction = float(cs.TAKE_PROFIT_SELL_PCT)
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
        if reason == "FLUCTUATION":
            ctx_getter = getattr(prot, "get_last_fluctuation_context", None)
            ctx = ctx_getter() if callable(ctx_getter) else {}
            sell_fraction = float(
                ctx.get(
                    "sell_fraction",
                    getattr(prot, "PROTECTION_FLUCTUATION_SELL_FRACTION", sell_fraction),
                )
            )
            sell_fraction = max(0.0, min(1.0, sell_fraction))
            usdt = float(ctx.get("usdt", 0.0))
            usdt_threshold = float(ctx.get("usdt_threshold", 0.0))
            wmatic_min = float(ctx.get("wmatic_min", 0.0))
            trigger_wmatic = float(ctx.get("wmatic", wmatic_balance))
            sell_amount = float(ctx.get("sell_amount_wmatic", 0.0))
            sell_notional = float(ctx.get("sell_notional_usd", 0.0))
            min_sell_usd = float(ctx.get("min_sell_usd", 0.0))
            message = (
                f"🛡️ PROTECTION TRIGGERED: {reason} — Force selling | "
                f"USDT=${usdt:.2f} (<${usdt_threshold:.2f}) | "
                f"WMATIC={trigger_wmatic:.4f} (min>{wmatic_min:.4f}) | "
                f"sell={sell_fraction * 100:.0f}% (~{sell_amount:.4f} WMATIC) | "
                f"notional=${sell_notional:.2f} (min=${min_sell_usd:.2f})"
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
