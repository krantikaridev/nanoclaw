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
from pathlib import Path
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
POL_AUTO_TOPUP_COOLDOWN_SECONDS = cfg.POL_AUTO_TOPUP_COOLDOWN_SECONDS
POL_MIN_BALANCE_FOR_TOPUP_TX = cfg.POL_MIN_BALANCE_FOR_TOPUP_TX
POL_SWAP_GAS_UNITS = cfg.POL_SWAP_GAS_UNITS
POL_EXECUTION_GAS_UNITS = cfg.POL_EXECUTION_GAS_UNITS
POL_EXECUTION_GAS_MULTIPLIER = cfg.POL_EXECUTION_GAS_MULTIPLIER
POL_APPROVE_GAS_UNITS = cfg.POL_APPROVE_GAS_UNITS
POL_UNWRAP_GAS_UNITS = cfg.POL_UNWRAP_GAS_UNITS
POL_GAS_RESERVE_MULTIPLIER = cfg.POL_GAS_RESERVE_MULTIPLIER
POL_GAS_RESERVE_BUFFER_POL = cfg.POL_GAS_RESERVE_BUFFER_POL
COPY_TRADE_PCT = cfg.COPY_TRADE_PCT
MAX_GWEI = cfg.MAX_GWEI
URGENT_GWEI = cfg.URGENT_GWEI
MIN_TRADE_USD = cfg.MIN_TRADE_USD
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
X_SIGNAL_EQUITY_DUST_MIN_USD = cfg.X_SIGNAL_EQUITY_DUST_MIN_USD
X_SIGNAL_MAX_EARNINGS_DAYS = cfg.X_SIGNAL_MAX_EARNINGS_DAYS
X_SIGNAL_FORCE_HIGH_CONVICTION = cfg.X_SIGNAL_FORCE_HIGH_CONVICTION
X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = cfg.X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD
X_SIGNAL_STRONG_THRESHOLD = cfg.X_SIGNAL_STRONG_THRESHOLD
X_SIGNAL_ROTATION_PRIORITY_THRESHOLD = cfg.X_SIGNAL_ROTATION_PRIORITY_THRESHOLD
X_SIGNAL_ROTATION_MIN_UPSIDE_PCT = cfg.X_SIGNAL_ROTATION_MIN_UPSIDE_PCT
X_SIGNAL_MIN_ACTIONABLE_STRENGTH = cfg.X_SIGNAL_MIN_ACTIONABLE_STRENGTH
X_SIGNAL_MIN_UPSIDE_PCT_FOR_WEAK = cfg.X_SIGNAL_MIN_UPSIDE_PCT_FOR_WEAK
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = cfg.X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC = cfg.X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC = cfg.X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC
FOLLOWED_EQUITIES_PATH = cfg.FOLLOWED_EQUITIES_PATH
FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY = cfg.FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY
FE_USD_SPOT_CACHE_FILE = ".runtime/fe_usd_spot_cache.json"
X_SIGNAL_USDC_MIN = cfg.X_SIGNAL_USDC_MIN
X_SIGNAL_WMATIC_MIN_VALUE = cfg.X_SIGNAL_WMATIC_MIN_VALUE
AUTO_POPULATE_USDC_AMOUNT = cfg.AUTO_POPULATE_USDC_AMOUNT
AUTO_USDC_FOR_X_SIGNAL_MIN_USDC = cfg.AUTO_USDC_FOR_X_SIGNAL_MIN_USDC
AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE = cfg.AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE
X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT = cfg.X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT
X_SIGNAL_USDC_SAFE_FLOOR = cfg.X_SIGNAL_USDC_SAFE_FLOOR
X_SIGNAL_AUTO_USDC_TARGET = cfg.X_SIGNAL_AUTO_USDC_TARGET
X_SIGNAL_AUTO_USDC_TOPUP_ENABLED = cfg.X_SIGNAL_AUTO_USDC_TOPUP_ENABLED
X_SIGNAL_AUTO_USDC_MIN_SWAP_USD = cfg.X_SIGNAL_AUTO_USDC_MIN_SWAP_USD
X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS = cfg.X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS


def _nanolog() -> str:
    p = (LOG_PREFIX or "").strip()
    return f"{p} " if p else ""


# region agent log
_AGENT_DEBUG_LOG = Path(__file__).resolve().parents[1] / "debug-0a457c.log"


def _agent_debug_ndjson(payload: dict) -> None:
    """Append one NDJSON line for debug-mode investigation (session 0a457c)."""
    try:
        row = {
            "sessionId": "0a457c",
            "timestamp": int(time.time() * 1000),
            **payload,
        }
        with _AGENT_DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


# endregion


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
_ASSET_LAST_TRADE_STATE_KEY = "asset_last_trade_unix"


@dataclass(frozen=True)
class Balances:
    usdt: float
    wmatic: float
    pol: float
    usdc: float = 0.0
    # Mark-to-USDT (router quote) for followed equity tokens (WETH/LINK/...) not in core balances; bug fix 2026-05-03
    followed_equity_usd: float = 0.0
    # Operator visibility (Cleanup #3, May 2026): pol × POL_USD_PRICE, the exact USD slice POL
    # contributes to ``total_portfolio_usd``. POL was already in TOTAL pre-cleanup, but the
    # ``WALLET TOTAL USD`` log line only printed POL quantity, so operators reconciling
    # against MetaMask had to back-solve POL_USD from the gap. Now it is a first-class field.
    pol_usd: float = 0.0
    # usdt+usdc+WMATIC*px+POL*px+followed_equity_usd; for dashboard / nanomon when liquid stables are 0 but positions exist
    total_portfolio_usd: float = 0.0


def compute_authoritative_total_usd(balances: "Balances") -> float:
    """Single source of truth for WALLET TOTAL USD across log / CSV / pnl_report.

    Authoritative formula:
        USDT + USDC(.e + native combined) + WMATIC*price_wmatic_usd
        + POL*POL_USD_PRICE + FE_USD

    The formula is materialized into ``Balances.total_portfolio_usd`` by
    ``get_balances()`` and ``write_portfolio_history_snapshot``; this helper is the
    canonical READ accessor.  Every operator-facing TOTAL surface (the
    ``WALLET TOTAL USD`` line in ``real_cron.log``, ``portfolio_history.csv``'s
    ``total_value`` column, and ``scripts/pnl_report.py``) MUST go through this
    helper rather than reading the field directly so the four touchpoints cannot
    drift silently — exactly the symptom that hid the May 2026 LINK_ALPHA FE_USD
    undercount for hours.
    """
    return float(balances.total_portfolio_usd)


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
    signal_strength: Optional[float] = None
    # Conservative planning gross edge % (net-edge filter); set by X-SIGNAL orchestration when known.
    expected_gross_edge_pct: Optional[float] = None
    # TEMPORARY (48-hour sprint): set on X-SIGNAL USDC→equity BUYs that passed $18 effective gate.
    x_signal_gated_execution: bool = False

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


def asset_cooldown_remaining_seconds(
    symbol: str,
    now: Optional[float] = None,
    cooldown_seconds: int = 0,
) -> float:
    """Seconds until per-asset cooldown elapses (0 when ready)."""
    current_time = time.time() if now is None else now
    last = float(ASSET_LAST_TRADE.get(symbol, 0) or 0)
    remain = float(cooldown_seconds) - (current_time - last)
    return max(0.0, remain)


def can_trade_asset(symbol: str, now: Optional[float] = None, cooldown_seconds: int = 0) -> bool:
    return asset_cooldown_remaining_seconds(symbol, now=now, cooldown_seconds=cooldown_seconds) <= 0.0


def mark_asset_traded(symbol: str, now: Optional[float] = None, cooldown_seconds: int = 0) -> None:
    ASSET_LAST_TRADE[symbol] = time.time() if now is None else now
    if cooldown_seconds:
        print(f"📌 Asset {symbol} cooldown started ({int(cooldown_seconds)}s)")


def _hydrate_asset_last_trade_from_state(state: dict) -> None:
    """Restore per-asset cooldown timestamps from ``bot_state.json`` (cron is one process per cycle)."""
    raw = state.get(_ASSET_LAST_TRADE_STATE_KEY)
    if not isinstance(raw, dict):
        return
    for sym, ts in raw.items():
        key = str(sym).strip()
        if not key:
            continue
        try:
            ASSET_LAST_TRADE[key] = float(ts)
        except (TypeError, ValueError):
            continue


def _persist_asset_last_trade_to_state(state: dict) -> None:
    if ASSET_LAST_TRADE:
        state[_ASSET_LAST_TRADE_STATE_KEY] = {
            str(k): float(v) for k, v in ASSET_LAST_TRADE.items()
        }


# Cleanup #3 (May 2026): per-(token, wallet) latch of tokens whose ``balanceOf``
# has already raised once. Symbols in ``.xsignal_blocked_symbols`` skip the
# FE_USD inventory ``balanceOf`` entirely (same blocklist as X-SIGNAL trading).
# For other unreadable contracts, the loop used to emit ``BALANCE READ FAILED``
# every cycle indefinitely — a few hundred lines/day of operator noise per
# broken contract. Now we log the failure once per (token, wallet) pair per
# process lifetime, then suppress.
_BALANCE_READ_FAIL_LOGGED: set[tuple[str, str]] = set()


def _reset_balance_read_fail_logged() -> None:
    """Test helper: clear the once-logged latch between cases."""
    _BALANCE_READ_FAIL_LOGGED.clear()


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
    except Exception as exc:
        key = (str(token_a).lower(), str(wallet_a).lower())
        if key in _BALANCE_READ_FAIL_LOGGED:
            return 0.0
        _BALANCE_READ_FAIL_LOGGED.add(key)
        err_s = str(exc).strip().replace("\n", " ")
        if len(err_s) > 220:
            err_s = err_s[:217] + "..."
        t_disp = f"{token_a[:10]}…{token_a[-6:]}" if len(str(token_a)) > 20 else str(token_a)
        w_disp = f"{wallet_a[:10]}…{wallet_a[-6:]}" if len(str(wallet_a)) > 20 else str(wallet_a)
        print(
            f"{_nanolog()}BALANCE READ FAILED | token={t_disp} | wallet={w_disp} | "
            f"{type(exc).__name__}: {err_s} | "
            f"(further failures for this token+wallet suppressed for process lifetime)"
        )
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


_AUTO_POL_FAILURE_STATE: dict[str, float] = {
    "next_retry_ts": 0.0,
    "consecutive_failures": 0.0,
}


def _pol_topup_min_usdt_swap() -> float:
    return max(5.0, float(MIN_TRADE_USD))


def estimate_pol_gas_cost_pol(
    *,
    gas_units: int,
    gas_gwei: float | None = None,
    multiplier: float = 1.0,
) -> float:
    """Native POL cost for ``gas_units`` at ``gas_gwei`` (defaults to live network price)."""
    gwei = float(gas_gwei if gas_gwei is not None else GAS_PROTECTOR.get_gas_price_gwei())
    return (int(gas_units) * gwei * 1e9 / 1e18) * float(multiplier)


def effective_pol_floor(*, urgent: bool = True, gas_gwei: float | None = None) -> float:
    """Operating POL floor: max(static MIN_POL_FOR_GAS, dynamic swap-gas reserve at urgent gwei)."""
    gwei = float(gas_gwei if gas_gwei is not None else GAS_PROTECTOR.get_gas_price_gwei())
    if urgent:
        gwei = max(gwei, float(URGENT_GWEI))
    dynamic = (
        estimate_pol_gas_cost_pol(
            gas_units=int(POL_SWAP_GAS_UNITS),
            gas_gwei=gwei,
            multiplier=float(POL_GAS_RESERVE_MULTIPLIER),
        )
        + float(POL_GAS_RESERVE_BUFFER_POL)
    )
    return max(float(MIN_POL_FOR_GAS), dynamic)


def _pol_operating_floor(explicit_min: float | None = None, *, urgent: bool = True) -> float:
    static = float(MIN_POL_FOR_GAS if explicit_min is None else explicit_min)
    return max(static, effective_pol_floor(urgent=urgent))


def _pol_execution_reserve(
    *,
    gas_units: int | None = None,
    gas_gwei: float | None = None,
) -> float:
    """POL for approve+swap at live gas (can exceed POL_SWAP_GAS_UNITS floor alone)."""
    units = int(gas_units if gas_units is not None else POL_EXECUTION_GAS_UNITS)
    mult = max(1.0, float(POL_EXECUTION_GAS_MULTIPLIER))
    return estimate_pol_gas_cost_pol(
        gas_units=units,
        gas_gwei=gas_gwei,
        multiplier=mult,
    )


def _pol_target_for_trade(
    explicit_min: float | None = None,
    *,
    urgent: bool = True,
    gas_units: int | None = None,
) -> float:
    """Target POL before broadcasting approve+swap."""
    floor = _pol_operating_floor(explicit_min, urgent=urgent)
    if not urgent:
        return floor
    return max(floor, _pol_execution_reserve(gas_units=gas_units))


def pol_can_broadcast_tx(*, gas_units: int, pol_balance: float | None = None) -> bool:
    pol = float(pol_balance if pol_balance is not None else get_pol_balance())
    need = estimate_pol_gas_cost_pol(gas_units=int(gas_units), multiplier=1.05)
    return pol + 1e-12 >= need


def _pol_min_for_topup_broadcast() -> float:
    return max(
        float(POL_MIN_BALANCE_FOR_TOPUP_TX),
        estimate_pol_gas_cost_pol(gas_units=int(POL_UNWRAP_GAS_UNITS), multiplier=1.05),
    )


def maybe_auto_topup_pol(
    min_pol: Optional[float] = None,
    *,
    context: str = "cycle",
    force: bool = False,
    min_gas_units: int | None = None,
) -> bool:
    """Proactive POL maintenance: top up when below trade target (floor + execution gas estimate)."""
    target = _pol_target_for_trade(min_pol, urgent=True, gas_units=min_gas_units)
    current_pol = float(get_pol_balance())

    if not AUTO_TOPUP_POL:
        print(
            f"{_nanolog()}AUTO-POL skipped — disabled (AUTO_TOPUP_POL=false, context={context}) "
            f"| pol≈{current_pol:.4f} | target={target:.4f}"
        )
        return current_pol >= target

    if current_pol >= target:
        print(
            f"{_nanolog()}AUTO-POL skipped — POL sufficient (context={context}) "
            f"| pol≈{current_pol:.4f} | target={target:.4f}"
        )
        return True

    now_ts = time.time()
    backoff_until = float(_AUTO_POL_FAILURE_STATE.get("next_retry_ts", 0.0) or 0.0)
    if not force and backoff_until > now_ts:
        remain_s = max(0.0, backoff_until - now_ts)
        print(
            f"{_nanolog()}AUTO-POL skipped — failure cooldown (context={context}) "
            f"| pol≈{current_pol:.4f} | target={target:.4f} | retry_in≈{remain_s:.0f}s"
        )
        return False

    print(
        f"{_nanolog()}AUTO-POL consider (context={context}) "
        f"| pol≈{current_pol:.4f} | target={target:.4f}"
    )
    ok = ensure_pol_for_trade(min_pol=min_pol, min_gas_units=min_gas_units)
    if ok:
        _AUTO_POL_FAILURE_STATE["next_retry_ts"] = 0.0
        _AUTO_POL_FAILURE_STATE["consecutive_failures"] = 0.0
        return True

    cooldown_s = max(0, int(POL_AUTO_TOPUP_COOLDOWN_SECONDS))
    if cooldown_s > 0:
        prev = int(_AUTO_POL_FAILURE_STATE.get("consecutive_failures", 0.0) or 0.0)
        _AUTO_POL_FAILURE_STATE["consecutive_failures"] = float(prev + 1)
        _AUTO_POL_FAILURE_STATE["next_retry_ts"] = now_ts + float(cooldown_s)
        print(
            f"{_nanolog()}AUTO-POL backoff set (context={context}) "
            f"| failures={prev + 1} | cooldown_s={cooldown_s}"
        )
    return False


def ensure_pol_for_trade(
    min_pol: float | None = None,
    *,
    min_gas_units: int | None = None,
) -> bool:
    current_pol = float(get_pol_balance())
    target = _pol_target_for_trade(min_pol, urgent=True, gas_units=min_gas_units)
    if current_pol >= target:
        print(
            f"{_nanolog()}AUTO-POL skipped — POL sufficient "
            f"| pol≈{current_pol:.4f} | target={target:.4f}"
        )
        return True

    min_pol_for_tx = _pol_min_for_topup_broadcast()
    if current_pol < min_pol_for_tx:
        print(
            f"{_nanolog()}AUTO-POL skipped — POL too low to broadcast top-up txs "
            f"(pol≈{current_pol:.6f} < {min_pol_for_tx:.4f}); send native POL manually once, "
            f"then AUTO-POL can unwrap WMATIC"
        )
        return False

    key, _key_source = cfg.resolve_private_key(log_success=True)
    if not key:
        print(f"{_nanolog()}AUTO-POL skipped — no private key")
        return False

    needed_pol = max(0.0, target - current_pol)
    # Target enough unwrap to clear execution reserve, not just POL_TOPUP_AMOUNT.
    desired_topup_pol = max(float(POL_TOPUP_AMOUNT), needed_pol + 0.005)
    print(
        f"🔄 AUTO-POL | Topping up ~{desired_topup_pol:.4f} POL "
        f"(current≈{current_pol:.4f}, target={target:.4f})"
    )
    balances = get_balances()
    usdt_swap_amount = min(8.0, float(balances.usdt) * 0.95)
    min_usdt_swap = _pol_topup_min_usdt_swap()

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

    if balances.wmatic < desired_topup_pol and usdt_swap_amount >= min_usdt_swap:
        print(
            f"{_nanolog()}AUTO-POL | USDT→WMATIC leg | usdt≈${usdt_swap_amount:.2f} "
            f"(min_swap=${min_usdt_swap:.2f})"
        )
        ok = _run(_swap_usdt_to_wmatic(int(usdt_swap_amount * 1_000_000)))
        if not ok:
            print(f"{_nanolog()}AUTO-POL warn — USDT→WMATIC leg failed, trying WMATIC unwrap fallback")
        balances = get_balances()
    elif balances.wmatic < desired_topup_pol:
        print(
            f"{_nanolog()}AUTO-POL skipped USDT→WMATIC — "
            f"usdt≈${usdt_swap_amount:.2f} below min_swap=${min_usdt_swap:.2f}; "
            f"wmatic≈{float(balances.wmatic):.4f}"
        )

    unwrap_pol = min(desired_topup_pol, float(balances.wmatic) * 0.95)
    if unwrap_pol <= 0:
        print(
            f"{_nanolog()}AUTO-POL skipped — insufficient WMATIC/USDT for top-up "
            f"(wmatic≈{float(balances.wmatic):.4f}, usdt≈${float(balances.usdt):.2f})"
        )
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
        if final_pol >= target:
            print(
                f"✅ AUTO-POL | Top-up successful "
                f"(pol≈{final_pol:.4f}, target={target:.4f}, unwrap≈{unwrap_pol:.4f})"
            )
            return True
        print(
            f"{_nanolog()}AUTO-POL failed — POL still low "
            f"(pol≈{final_pol:.4f}, need≥{target:.4f})"
        )
        return False
    except Exception as e:
        print(f"{_nanolog()}AUTO-POL failed — {e}")
        return False


def get_gas_status(
    urgent: bool = False,
    protector: GasProtector = GAS_PROTECTOR,
    wallet_address: str = WALLET,
    min_pol: Optional[float] = None,
) -> dict:
    pol_floor = float(min_pol if min_pol is not None else effective_pol_floor(urgent=urgent))
    return protector.get_safe_status(
        address=wallet_address,
        urgent=urgent,
        min_pol=pol_floor,
    )


def fixed_copy_trade_usd(usdc: float, usdt: float, copy_trade_pct: float) -> float:
    # FIXED SIZING: band per signal — bounds from FIXED_TRADE_USD_MIN / FIXED_TRADE_USD_MAX (.env).
    stable = max(0.0, float(usdc)) + max(0.0, float(usdt))
    raw = stable * float(copy_trade_pct)
    lo, hi = FIXED_TRADE_USD_MIN, FIXED_TRADE_USD_MAX
    if hi < lo:
        lo, hi = hi, lo
    return max(lo, min(hi, float(raw)))


def _quote_followed_token_usdt_mtm(
    web3_client: Web3,
    *,
    token_in: str,
    amount_in_raw: int,
    slippage_bps: int,
) -> float:
    """USDT notional (human, 6 decimals) for FE_USD: V2 router, QuoterV2 single-hop, legacy Quoter, then QuoterV2 multi-hop."""
    if amount_in_raw <= 0:
        return 0.0
    from web3 import Web3 as Web3Local

    from nanoclaw.abi.uniswap_v3_abi import UNISWAP_V3_QUOTER_ABI
    from nanoclaw.execution.uniswap_v3_helpers import quote_exact_input_single
    from swap_executor import _best_quote_path, build_polygon_swap_path_candidates

    slip = int(slippage_bps)
    t_in = Web3Local.to_checksum_address(str(token_in).strip())
    t_usdt = Web3Local.to_checksum_address(str(USDT).strip())
    paths = build_polygon_swap_path_candidates(t_in, t_usdt)
    try:
        _path, best_amt, _min_out = _best_quote_path(
            web3_client,
            router=ROUTER,
            amount_in=int(amount_in_raw),
            paths=paths,
            slippage_bps=slip,
        )
        if best_amt > 0:
            return float(best_amt) / 1_000_000.0
    except Exception:
        pass

    best_v3 = 0
    quoter_v1 = str(cfg.UNISWAP_V3_QUOTER).strip()
    quoter_v2 = str(cfg.UNISWAP_V3_QUOTER_V2).strip()
    from nanoclaw.execution.uniswap_v3_helpers import quote_exact_input_single_quoterv2

    for fee in (500, 3000, 10000):
        got = 0
        if quoter_v2:
            try:
                got = int(
                    quote_exact_input_single_quoterv2(
                        web3_client,
                        quoter_address=quoter_v2,
                        token_in=t_in,
                        token_out=t_usdt,
                        amount_in=int(amount_in_raw),
                        fee=int(fee),
                    )
                )
            except Exception:
                got = 0
        if got <= 0 and quoter_v1:
            try:
                amt_out, _mn = quote_exact_input_single(
                    web3_client,
                    quoter_address=quoter_v1,
                    quoter_abi=UNISWAP_V3_QUOTER_ABI,
                    token_in=t_in,
                    token_out=t_usdt,
                    amount_in=int(amount_in_raw),
                    slippage_bps=slip,
                    fee=int(fee),
                )
                got = int(amt_out)
            except Exception:
                got = 0
        if got > best_v3:
            best_v3 = got
    if best_v3 <= 0 and quoter_v2:
        from nanoclaw.execution.uniswap_v3_helpers import (
            encode_uniswap_v3_path,
            quote_exact_input_multihop_quoterv2,
        )

        t_usdc = Web3Local.to_checksum_address(str(USDC).strip())
        wm = Web3Local.to_checksum_address(str(WMATIC).strip())
        hop_candidates: list[tuple[list[str], list[int]]] = [
            ([t_in, t_usdc, t_usdt], [500, 500]),
            ([t_in, t_usdc, t_usdt], [500, 3000]),
            ([t_in, t_usdc, t_usdt], [3000, 500]),
            ([t_in, t_usdc, t_usdt], [3000, 3000]),
            ([t_in, t_usdc, t_usdt], [500, 100]),
            ([t_in, t_usdc, t_usdt], [3000, 100]),
            ([t_in, t_usdc, t_usdt], [10000, 500]),
            ([t_in, wm, t_usdt], [500, 500]),
            ([t_in, wm, t_usdt], [3000, 500]),
            ([t_in, wm, t_usdt], [500, 3000]),
            ([t_in, wm, t_usdt], [3000, 3000]),
        ]
        seen_paths: set[bytes] = set()
        for toks, fees in hop_candidates:
            try:
                pbytes = encode_uniswap_v3_path(toks, fees)
                if pbytes in seen_paths:
                    continue
                seen_paths.add(pbytes)
                got = quote_exact_input_multihop_quoterv2(
                    web3_client,
                    quoter_address=quoter_v2,
                    path=pbytes,
                    amount_in=int(amount_in_raw),
                )
                if got > best_v3:
                    best_v3 = got
            except Exception:
                continue
    # region agent log
    out_usdt = float(best_v3) / 1_000_000.0 if best_v3 > 0 else 0.0
    try:
        _agent_debug_ndjson(
            {
                "hypothesisId": "H2",
                "location": "runtime._quote_followed_token_usdt_mtm:exit",
                "message": "followed token MTM quote",
                "data": {
                    "token_in_tail": str(t_in)[-12:],
                    "amount_in_raw": int(amount_in_raw),
                    "best_v3_raw": int(best_v3),
                    "out_usdt": float(out_usdt),
                },
            }
        )
    except Exception:
        pass
    # endregion
    return out_usdt


def _fe_usd_spot_cache_path() -> Path:
    return Path(FE_USD_SPOT_CACHE_FILE)


def _load_fe_usd_spot_cache() -> dict:
    path = _fe_usd_spot_cache_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_fe_usd_spot_cache(cache: dict) -> None:
    path = _fe_usd_spot_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2)


def _cached_fe_usd_spot(cache: dict, symbol: str) -> float | None:
    entry = cache.get(str(symbol).strip())
    if not isinstance(entry, dict):
        return None
    try:
        spot = float(entry.get("spot_usd"))
    except (TypeError, ValueError):
        return None
    return spot if spot > 0 else None


def _effective_fe_usd_floor_px(json_floor_px: float, cached_spot_px: float | None) -> float:
    """``min(json_floor, last_good_spot)`` when cache exists; else JSON floor only."""
    if cached_spot_px is not None and cached_spot_px > 0:
        if json_floor_px > 0:
            return min(json_floor_px, cached_spot_px)
        return cached_spot_px
    return json_floor_px


def _spot_for_fe_usd_effective_floor(
    json_floor_px: float,
    prior_cached_spot: float | None,
    live_spot: float | None,
) -> float:
    """Prior cache anchors floor; first run with live uses live spot vs stale JSON."""
    if prior_cached_spot is not None and prior_cached_spot > 0:
        return _effective_fe_usd_floor_px(json_floor_px, prior_cached_spot)
    if live_spot is not None and live_spot > 0:
        return _effective_fe_usd_floor_px(json_floor_px, live_spot)
    return json_floor_px


def _capped_fe_usd_spot_persist(
    live_spot: float,
    prior_spot: float | None,
    prior_updated_unix: float | None,
    *,
    now: float | None = None,
) -> float:
    """Cap upward cache drift per day; downward moves from live always apply."""
    if live_spot <= 0:
        return live_spot
    if prior_spot is None or prior_spot <= 0 or live_spot <= prior_spot:
        return live_spot
    ts = time.time() if now is None else float(now)
    if prior_updated_unix is not None:
        elapsed_days = max((ts - float(prior_updated_unix)) / 86400.0, 1.0)
    else:
        elapsed_days = 1.0
    max_up = float(FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY) / 100.0
    max_allowed = prior_spot * (1.0 + max_up * elapsed_days)
    return min(live_spot, max_allowed)


def _maybe_persist_fe_usd_spot_from_live(
    cache: dict,
    symbol: str,
    live_quote_usdt: float,
    balance: float,
    *,
    now: float | None = None,
) -> tuple[float | None, bool]:
    """Persist last-good spot from a successful live quote; return (spot, cache_dirty)."""
    sym = str(symbol).strip()
    if live_quote_usdt <= 0 or balance <= 0:
        return _cached_fe_usd_spot(cache, sym), False
    live_spot = float(live_quote_usdt) / float(balance)
    entry = cache.get(sym)
    prior_spot: float | None = None
    prior_ts: float | None = None
    if isinstance(entry, dict):
        try:
            if entry.get("spot_usd") is not None:
                prior_spot = float(entry.get("spot_usd"))
        except (TypeError, ValueError):
            prior_spot = None
        try:
            if entry.get("updated_unix") is not None:
                prior_ts = float(entry.get("updated_unix"))
        except (TypeError, ValueError):
            prior_ts = None
    persist_spot = _capped_fe_usd_spot_persist(
        live_spot, prior_spot, prior_ts, now=now
    )
    if prior_spot is not None and abs(float(persist_spot) - float(prior_spot)) <= 1e-9:
        return float(prior_spot), False
    ts = time.time() if now is None else float(now)
    cache[sym] = {"spot_usd": float(persist_spot), "updated_unix": ts}
    return float(persist_spot), True


def _followed_equity_tokens_usdt_usd() -> float:
    """Router-quoted USDT value for non-core followed tokens (excludes USDC/USDT/WMATIC already in Balances)."""
    total = 0.0
    fe_spot_cache = _load_fe_usd_spot_cache()
    fe_spot_cache_dirty = False
    # region agent log
    wf = ""
    try:
        w = str(WALLET).strip()
        if len(w) >= 10:
            wf = f"{w[:6]}…{w[-4:]}"
    except Exception:
        wf = ""
    # endregion
    try:
        assets = X_SIGNAL_EQUITY_TRADER.load_followed_equities()
    except Exception as exc:
        # region agent log
        _agent_debug_ndjson(
            {
                "hypothesisId": "H3",
                "location": "runtime._followed_equity_tokens_usdt_usd:load",
                "message": "load_followed_equities failed",
                "data": {"err_type": type(exc).__name__, "err": str(exc)[:120]},
            }
        )
        # endregion
        return 0.0
    from modules import signal as signal_module

    blocked_syms, _ = signal_module.load_xsignal_blocked_symbols()
    # region agent log
    _agent_debug_ndjson(
        {
            "hypothesisId": "H3",
            "location": "runtime._followed_equity_tokens_usdt_usd:entry",
            "message": "followed equities scan",
            "data": {
                "n_assets": len(assets),
                "followed_path": str(FOLLOWED_EQUITIES_PATH),
                "wallet_fingerprint": wf,
            },
        }
    )
    # endregion
    for a in assets:
        addr = (a.token_address or "").strip()
        sym = str(getattr(a, "symbol", "") or "").strip()
        if not addr:
            # region agent log
            _agent_debug_ndjson(
                {
                    "hypothesisId": "H3",
                    "location": "runtime._followed_equity_tokens_usdt_usd:asset",
                    "message": "skip asset",
                    "data": {"symbol": sym, "reason": "no_addr"},
                }
            )
            # endregion
            continue
        al = addr.lower()
        core_tokens = {USDC.lower(), USDT.lower(), WMATIC.lower()}
        native = (USDC_NATIVE or "").strip().lower()
        if native:
            core_tokens.add(native)
        if al in core_tokens:
            # region agent log
            _agent_debug_ndjson(
                {
                    "hypothesisId": "H4",
                    "location": "runtime._followed_equity_tokens_usdt_usd:asset",
                    "message": "skip core token",
                    "data": {"symbol": sym, "addr_tail": al[-8:]},
                }
            )
            # endregion
            continue
        if sym.upper() in blocked_syms:
            continue
        bal = get_token_balance(addr, int(a.decimals))
        if bal <= 0:
            # region agent log
            _agent_debug_ndjson(
                {
                    "hypothesisId": "H1",
                    "location": "runtime._followed_equity_tokens_usdt_usd:asset",
                    "message": "zero on-chain bal",
                    "data": {"symbol": sym, "addr_tail": al[-8:], "bal": float(bal)},
                }
            )
            # endregion
            continue
        amt = int(bal * (10 ** int(a.decimals)))
        if amt <= 0:
            # region agent log
            _agent_debug_ndjson(
                {
                    "hypothesisId": "H5",
                    "location": "runtime._followed_equity_tokens_usdt_usd:asset",
                    "message": "amount wei zero",
                    "data": {"symbol": sym, "addr_tail": al[-8:], "bal": float(bal), "amt": int(amt), "decimals": int(a.decimals)},
                }
            )
            # endregion
            continue
        slip = int(cfg.INVENTORY_MTM_SLIPPAGE_BPS)
        usdt_val = _quote_followed_token_usdt_mtm(w3, token_in=addr, amount_in_raw=amt, slippage_bps=slip)
        px = getattr(a, "current_price_usd", None)
        try:
            json_floor_px = float(px) if px is not None else 0.0
        except (TypeError, ValueError):
            json_floor_px = 0.0
        prior_cached_spot = _cached_fe_usd_spot(fe_spot_cache, sym)
        live_spot = (float(usdt_val) / float(bal)) if (usdt_val > 0 and bal > 0) else None
        effective_floor_px = _spot_for_fe_usd_effective_floor(
            json_floor_px, prior_cached_spot, live_spot
        )
        fallback_usd = float(bal) * effective_floor_px if (effective_floor_px > 0 and bal > 0) else 0.0
        # Only persist last-good spot when live confirms at/above the effective floor (Cleanup #3
        # degraded quotes must not poison prior cache on the same cycle we used it as floor).
        if usdt_val > 0 and bal > 0 and float(usdt_val) >= fallback_usd:
            persisted_spot, cache_updated = _maybe_persist_fe_usd_spot_from_live(
                fe_spot_cache, sym, float(usdt_val), float(bal)
            )
            if cache_updated:
                fe_spot_cache_dirty = True
                try:
                    print(
                        f"[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym={sym} | "
                        f"last_good_spot={persisted_spot:.4f} | json_floor={json_floor_px:.4f} | "
                        f"effective_floor={effective_floor_px:.4f}"
                    )
                except Exception:
                    pass
        # Cleanup #3 (May 2026): use ``current_price_usd`` as a FALLBACK FLOOR, not just a
        # zero-quote substitute. Pre-cleanup, the live quote always won when > 0, even if
        # it priced 5.676 LINK at $35.78 (~$6.30/LINK against a $9.43 spot fallback) — a
        # ~$18 silent undercount that operators only caught by reconciling against
        # MetaMask. After cleanup, the effective price is ``max(live_quote, fallback)``:
        #   * Healthy pool, fresh quote ≥ fallback → live wins (no change vs pre-cleanup).
        #   * Drained pool / large-size impact / stale quote < fallback → fallback floor
        #     wins, TOTAL stays anchored to a known good operator-curated spot price.
        # P1 (May 2026): ``effective_floor_px`` = min(JSON floor, last-good cached spot) so
        # stale JSON above spot cannot overstate TOTAL when a healthy live quote exists.
        effective_usd = max(float(usdt_val), fallback_usd)
        total += effective_usd
        if usdt_val <= 0 and fallback_usd <= 0:
            # Zero live quote AND no fallback configured: position is invisible to TOTAL.
            try:
                print(
                    f"[nanoclaw] FE_USD UNQUOTED | sym={sym} | "
                    f"bal={float(bal):.6f} | live_quote_usdt=$0.00 | "
                    f"fallback_px_usd={effective_floor_px:.4f} | "
                    f"contributed_to_total=$0.00 | "
                    f"action: refresh `current_price_usd` in followed_equities.json or fix on-chain quote path"
                )
            except Exception:
                pass
        elif usdt_val <= 0 and fallback_usd > 0:
            # Existing diagnostic (Cleanup pre-#3): no live quote, fallback carries TOTAL.
            try:
                print(
                    f"[nanoclaw] FE_USD UNQUOTED | sym={sym} | "
                    f"bal={float(bal):.6f} | live_quote_usdt=$0.00 | "
                    f"fallback_px_usd={effective_floor_px:.4f} | "
                    f"contributed_to_total=${fallback_usd:.2f} | "
                    f"action: refresh `current_price_usd` in followed_equities.json or fix on-chain quote path"
                )
            except Exception:
                pass
        elif fallback_usd > usdt_val:
            # Cleanup #3 (May 2026): live quote came back lower than fallback × bal. This
            # is the May 2026 LINK_ALPHA symptom — operator-visible diagnostic so the gap
            # against MetaMask is logged at the moment it happens, not back-solved later.
            try:
                print(
                    f"[nanoclaw] FE_USD FALLBACK FLOOR APPLIED | sym={sym} | "
                    f"bal={float(bal):.6f} | live_quote_usdt=${float(usdt_val):.2f} | "
                    f"fallback_px_usd={effective_floor_px:.4f} | "
                    f"fallback_total_usd=${fallback_usd:.2f} | "
                    f"contributed_to_total=${effective_usd:.2f} | "
                    f"action: verify on-chain pool depth; refresh fallback when spot moves materially"
                )
            except Exception:
                pass
        # region agent log
        _agent_debug_ndjson(
            {
                "hypothesisId": "H2",
                "location": "runtime._followed_equity_tokens_usdt_usd:asset",
                "message": "fe leg priced",
                "data": {
                    "symbol": sym,
                    "bal": float(bal),
                    "amt": int(amt),
                    "usdt_val": float(usdt_val),
                    "fallback_usd": float(fallback_usd),
                    "effective_floor_px": float(effective_floor_px),
                    "effective_usd": float(effective_usd),
                },
            }
        )
        # endregion
    if fe_spot_cache_dirty:
        try:
            _save_fe_usd_spot_cache(fe_spot_cache)
        except Exception:
            pass
    # region agent log
    _agent_debug_ndjson(
        {
            "hypothesisId": "H1",
            "location": "runtime._followed_equity_tokens_usdt_usd:total",
            "message": "fe_usd total",
            "data": {"fe_usd": float(total)},
        }
    )
    # endregion
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
    pol_usd = pol * pol_price_usd
    total_pf = usdt + usdc + (wmatic * wmatic_px) + pol_usd + fe_usd
    return Balances(
        usdt=usdt,
        wmatic=wmatic,
        pol=pol,
        usdc=usdc,
        followed_equity_usd=fe_usd,
        pol_usd=pol_usd,
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
    # Cleanup #1 (May 2026): build a Balances snapshot and read TOTAL through the
    # canonical helper so the CSV ``total_value`` column never drifts from the
    # ``WALLET TOTAL USD`` log line / pnl_report. Formula write site mirrors
    # ``get_balances()``; if you change one, change both (and update tests).
    pol_usd = pol * pol_price_usd
    balances_snapshot = Balances(
        usdt=usdt,
        wmatic=wmatic,
        pol=pol,
        usdc=usdc,
        followed_equity_usd=fe_usd,
        pol_usd=pol_usd,
        total_portfolio_usd=usdt + usdc + (wmatic * current_price) + pol_usd + fe_usd,
    )
    total_value = compute_authoritative_total_usd(balances_snapshot)
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
            state = json.load(file_handle)
    except Exception:
        state = {"last_run": 0}
    if not isinstance(state, dict):
        state = {"last_run": 0}
    _hydrate_asset_last_trade_from_state(state)
    return state


def save_state(state: dict, path: str = STATE_FILE) -> None:
    _persist_asset_last_trade_to_state(state)
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(state, file_handle, indent=2)


def _cycle_lock_seconds() -> int:
    return max(15, int(getattr(cfg, "NANOCLOW_CYCLE_LOCK_SECONDS", 300)))


def has_active_lock(
    lock_file: str = LOCK_FILE,
    now: Optional[float] = None,
    lock_seconds: int | None = None,
) -> bool:
    if not os.path.exists(lock_file):
        return False
    current_time = time.time() if now is None else now
    ttl = _cycle_lock_seconds() if lock_seconds is None else int(lock_seconds)
    return (current_time - os.path.getmtime(lock_file)) < ttl


def create_lock(lock_file: str = LOCK_FILE) -> None:
    with open(lock_file, "w", encoding="utf-8"):
        pass


def touch_lock(lock_file: str = LOCK_FILE) -> None:
    """Refresh lock mtime during long approve/swap so overlapping cron cannot start."""
    if os.path.exists(lock_file):
        os.utime(lock_file, None)


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


def evaluate_take_profit(
    current_price: float,
    state: dict,
    *,
    wmatic_balance: float | None = None,
) -> Tuple[bool, Optional[dict]]:
    cs = importlib.import_module("clean_swap")
    from .decision_log import log_profit_take_decision

    trade = cs.get_latest_open_trade()
    tracking = state.setdefault("profit_tracking", {})
    take_profit_pct, strong_signal_tp = cs._effective_take_profit_thresholds()

    def _log_tp(action: str, reason: str, *, signal: float | None = None, extra: str = "") -> None:
        log_profit_take_decision(
            action=action,
            reason=reason,
            signal_strength=signal,
            wmatic_balance=wmatic_balance,
            extra=extra,
            state=state,
        )

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
        _log_tp("TAKE", "STRONG_TP_HIT", signal=min(1.0, gain_pct / max(strong_signal_tp, 1e-9)), extra=f"gain_pct={gain_pct:.2f}")
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
        _log_tp("TAKE", "TP_HIT", signal=min(1.0, gain_pct / max(take_profit_pct, 1e-9)), extra=f"gain_pct={gain_pct:.2f}")
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
        _log_tp(
            "TAKE",
            "TRAILING_STOP_HIT",
            signal=min(1.0, peak_gain_pct / max(take_profit_pct, 1e-9)),
            extra=f"pullback_pct={pullback_pct:.2f}",
        )
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

    _log_tp("HOLD", "HOLD", signal=max(0.0, min(1.0, gain_pct / max(take_profit_pct, 1e-9))), extra=f"gain_pct={gain_pct:.2f}")
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
