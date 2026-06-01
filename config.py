"""Centralized environment configuration for nanoclaw."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name)
    if value is None:
        return "" if default is None else str(default)
    return str(value)


def env_str(name: str, default: str = "") -> str:
    return env(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name, None).strip()
    if raw == "":
        return bool(default)
    return raw.lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    raw = env(name, None).strip()
    if raw == "":
        return int(default)
    return int(raw)


def env_symbol_frozenset(name: str, default: str = "") -> frozenset[str]:
    """Comma/semicolon-separated symbol list (uppercased), e.g. ``WBTC_ALPHA,LINK_ALPHA``."""
    raw = env_str(name, default)
    if not raw:
        return frozenset()
    parts = [p.strip().upper() for p in raw.replace(";", ",").split(",") if p.strip()]
    return frozenset(parts)


def env_float(name: str, default: float) -> float:
    raw = env(name, None).strip()
    if raw == "":
        return float(default)
    return float(raw)


def reconcile_fixed_trade_min(min_trade_usd: float, fixed_trade_usd_min_raw: float) -> float:
    """Ensure strategy minimum cannot sit below global execution minimum."""
    return max(float(fixed_trade_usd_min_raw), float(min_trade_usd))


def parse_csv_urls(raw: str) -> list[str]:
    """Parse comma-separated URLs and drop empties while preserving order."""
    return [part.strip() for part in str(raw).split(",") if str(part).strip()]


def merge_unique_urls(*sources: list[str]) -> list[str]:
    """Merge URL lists preserving first-seen order and dropping duplicates."""
    merged: list[str] = []
    for urls in sources:
        for url in urls:
            normalized = str(url).strip()
            if not normalized or normalized in merged:
                continue
            merged.append(normalized)
    return merged


RPC = env_str("RPC", "https://polygon-rpc.com")
RPC_URL = env_str("RPC_URL", RPC or "https://polygon-rpc.com")
WEB3_PROVIDER_URI = env_str("WEB3_PROVIDER_URI", RPC or "https://polygon-rpc.com")
RPC_ENDPOINTS_RAW = env_str("RPC_ENDPOINTS", "")
RPC_ENDPOINTS = merge_unique_urls(
    parse_csv_urls(RPC_ENDPOINTS_RAW),
    [RPC, RPC_URL, WEB3_PROVIDER_URI],
)
RPC_FALLBACKS_RAW = env_str("RPC_FALLBACKS", "")
RPC_FALLBACKS = parse_csv_urls(RPC_FALLBACKS_RAW)

WALLET = env_str("WALLET", "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6")
POLYGON_PRIVATE_KEY = env_str("POLYGON_PRIVATE_KEY", "")
PRIVATE_KEY = env_str("PRIVATE_KEY", "")
# Backward-compatible fallback: prefer POLYGON_PRIVATE_KEY, then legacy PRIVATE_KEY.
RESOLVED_KEY = POLYGON_PRIVATE_KEY or PRIVATE_KEY

USDT = env_str("USDT", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F")
USDC_ADDRESS = env_str("USDC", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
USDC = USDC_ADDRESS
USDC_NATIVE_RAW = os.getenv("USDC_NATIVE")
USDC_NATIVE = (
    "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    if USDC_NATIVE_RAW is None
    else str(USDC_NATIVE_RAW).strip()
)
WMATIC = env_str("WMATIC", "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270")
ROUTER = env_str("ROUTER", "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")
QUICKSWAP_V2_ROUTER = env_str("QUICKSWAP_V2_ROUTER", "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")
UNISWAP_V3_SWAP_ROUTER = env_str("UNISWAP_V3_SWAP_ROUTER", "0xE592427A0AEce92De3Edee1F18E0157C05861564")
UNISWAP_V3_QUOTER = env_str("UNISWAP_V3_QUOTER", "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6")
UNISWAP_V3_QUOTER_V2 = env_str("UNISWAP_V3_QUOTER_V2", "0x61fFE014bA17989E743c5F6cB21bF9697530B21e")

LOG_PREFIX = env_str("LOG_PREFIX", "[nanoclaw]")
NO_COLOR = env_str("NO_COLOR", "")

COOLDOWN_MINUTES = env_int("COOLDOWN_MINUTES", 3)
# Cron overlap guard: lock file TTL while a cycle runs (approve+swap can exceed 15s).
NANOCLOW_CYCLE_LOCK_SECONDS = env_int("NANOCLOW_CYCLE_LOCK_SECONDS", 300)
PER_ASSET_COOLDOWN_MINUTES = env_int("PER_ASSET_COOLDOWN_MINUTES", 30)
PER_ASSET_COOLDOWN_SECONDS = PER_ASSET_COOLDOWN_MINUTES * 60
PER_WALLET_COOLDOWN = env_int("PER_WALLET_COOLDOWN", 180)
COPY_TRADING_ENABLED = env_bool("COPY_TRADING_ENABLED", True)
# Strip known Polygon token contracts from followed_wallets.json at runtime (see docs/COPY_TRADING_AUDIT.md).
COPY_TRADING_REJECT_TOKEN_CONTRACTS = env_bool("COPY_TRADING_REJECT_TOKEN_CONTRACTS", True)

POL_USD_PRICE = env_float("POL_USD_PRICE", 0.10)
# Code floor: stale VM .env values like 0.005 skip AUTO-POL until swaps fail on gas.
_MIN_POL_FOR_GAS_ENV = env_float("MIN_POL_FOR_GAS", 0.15)
MIN_POL_FOR_GAS = max(0.12, float(_MIN_POL_FOR_GAS_ENV))
AUTO_TOPUP_POL = env_bool("AUTO_TOPUP_POL", True)
POL_TOPUP_AMOUNT = env_float("POL_TOPUP_AMOUNT", 0.03)
# Backoff after a failed AUTO-POL attempt (seconds) to avoid tight retry loops.
POL_AUTO_TOPUP_COOLDOWN_SECONDS = env_int("POL_AUTO_TOPUP_COOLDOWN_SECONDS", 300)
# Minimum native POL required to broadcast unwrap/swap legs (below this, send POL manually once).
POL_MIN_BALANCE_FOR_TOPUP_TX = env_float("POL_MIN_BALANCE_FOR_TOPUP_TX", 0.006)
# Dynamic POL reserve: estimate swap gas at urgent gwei × multiplier (fixes stale low MIN_POL_FOR_GAS on VM).
POL_SWAP_GAS_UNITS = env_int("POL_SWAP_GAS_UNITS", 450_000)
# Approve + swap + receipt buffer for pre-trade POL top-up (must exceed POL_SWAP_GAS_UNITS reserve).
POL_EXECUTION_GAS_UNITS = env_int("POL_EXECUTION_GAS_UNITS", 600_000)
POL_APPROVE_GAS_UNITS = env_int("POL_APPROVE_GAS_UNITS", 85_000)
POL_UNWRAP_GAS_UNITS = env_int("POL_UNWRAP_GAS_UNITS", 140_000)
POL_GAS_RESERVE_MULTIPLIER = env_float("POL_GAS_RESERVE_MULTIPLIER", 1.30)
POL_EXECUTION_GAS_MULTIPLIER = env_float("POL_EXECUTION_GAS_MULTIPLIER", 1.15)
POL_GAS_RESERVE_BUFFER_POL = env_float("POL_GAS_RESERVE_BUFFER_POL", 0.005)
# Startup: skip force-max approve when allowance already sufficient; never crash on low POL.
FORCE_STARTUP_MAX_APPROVE = env_bool("FORCE_STARTUP_MAX_APPROVE", True)
COPY_TRADE_PCT = env_float("COPY_TRADE_PCT", 0.28)
DEFAULT_MAX_COPY_RATIO = env_float("DEFAULT_MAX_COPY_RATIO", 0.20)
MAX_GWEI = env_float("MAX_GWEI", 80.0)
URGENT_GWEI = env_float("URGENT_GWEI", 120.0)
GAS_RPC_RETRY_ATTEMPTS = env_int("GAS_RPC_RETRY_ATTEMPTS", 2)

MIN_TRADE_USD = env_float("MIN_TRADE_USD", env_float("MIN_TRADE_USDC", 5.0))
_FIXED_TRADE_USD_MIN_RAW = env_float("FIXED_TRADE_USD_MIN", MIN_TRADE_USD)
# Reconcile minima so strategy sizing cannot produce trades that the global execution guard will always reject.
FIXED_TRADE_USD_MIN = reconcile_fixed_trade_min(MIN_TRADE_USD, _FIXED_TRADE_USD_MIN_RAW)
FIXED_TRADE_USD_MAX = env_float("FIXED_TRADE_USD_MAX", 10.0)
TRAILING_STOP_PCT = env_float("TRAILING_STOP_PCT", 5.0)
TAKE_PROFIT_PCT = env_float("TAKE_PROFIT_PCT", 5.0)
# v1 quality filter: minimum estimated net edge (% of notional after gas/fees) for X-Signal / main entry trades.
MIN_NET_EDGE_PCT = env_float("MIN_NET_EDGE_PCT", 2.0)
# Reserve % of notional for swap fee/slippage before gas (subtracted from gross edge in planning).
MIN_NET_EDGE_FEE_BUFFER_PCT = env_float("MIN_NET_EDGE_FEE_BUFFER_PCT", 0.75)
# Conservative planning gas (gwei) for early net-edge gates in determine_trade_decision (no RPC).
NET_EDGE_PLANNING_GAS_GWEI = env_float("NET_EDGE_PLANNING_GAS_GWEI", 120.0)
# Main USDT→WMATIC entry: fraction of TAKE_PROFIT_PCT used as gross edge when MAIN_STRATEGY_ENTRY_EDGE_PCT=0.
MAIN_STRATEGY_ENTRY_EDGE_FRAC = env_float("MAIN_STRATEGY_ENTRY_EDGE_FRAC", 0.70)
# Optional override gross edge % for main entry (0 = use MAIN_STRATEGY_ENTRY_EDGE_FRAC × TAKE_PROFIT_PCT).
MAIN_STRATEGY_ENTRY_EDGE_PCT = env_float("MAIN_STRATEGY_ENTRY_EDGE_PCT", 0.0)
STRONG_SIGNAL_TP = env_float("STRONG_SIGNAL_TP", 12.0)
TAKE_PROFIT_SELL_PCT = env_float("TAKE_PROFIT_SELL_PCT", 0.45)
STRONG_TP_SELL_PCT = env_float("STRONG_TP_SELL_PCT", 0.60)

ENABLE_USDC_COPY = env_bool("ENABLE_USDC_COPY", False)
USDC_COPY_MIN_TRADE = env_float("USDC_COPY_MIN_TRADE", 5.0)
USDC_COPY_MAX_TRADE = env_float("USDC_COPY_MAX_TRADE", 15.0)

ENABLE_X_SIGNAL_EQUITY = env_bool("ENABLE_X_SIGNAL_EQUITY", False)
X_SIGNAL_EQUITY_MIN_STRENGTH = env_float("X_SIGNAL_EQUITY_MIN_STRENGTH", 0.60)
X_SIGNAL_MAX_EARNINGS_DAYS = env_float("X_SIGNAL_MAX_EARNINGS_DAYS", 5.0)
X_SIGNAL_FORCE_HIGH_CONVICTION = env_bool("X_SIGNAL_FORCE_HIGH_CONVICTION", True)
HIGH_CONVICTION_THRESHOLD = env_float("HIGH_CONVICTION_THRESHOLD", 0.82)
X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD = env_float(
    "X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD",
    HIGH_CONVICTION_THRESHOLD,
)
X_SIGNAL_STRONG_THRESHOLD = env_float("X_SIGNAL_STRONG_THRESHOLD", HIGH_CONVICTION_THRESHOLD)
# Signal-Driven Rotation (May 2026): cycle precedence / main deferral only — defaults to strong bar (no change unless set lower).
X_SIGNAL_ROTATION_PRIORITY_THRESHOLD = env_float(
    "X_SIGNAL_ROTATION_PRIORITY_THRESHOLD",
    X_SIGNAL_STRONG_THRESHOLD,
)
# Optional: force-eligible BUY also triggers rotation when upside_pct meets this (0 = strength-only).
X_SIGNAL_ROTATION_MIN_UPSIDE_PCT = env_float("X_SIGNAL_ROTATION_MIN_UPSIDE_PCT", 0.0)
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = env_float(
    "X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD",
    X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
)
# Quality filter (0 disables): drop non-force-eligible assets below actionable strength / upside.
X_SIGNAL_MIN_ACTIONABLE_STRENGTH = env_float("X_SIGNAL_MIN_ACTIONABLE_STRENGTH", 0.0)
X_SIGNAL_MIN_UPSIDE_PCT_FOR_WEAK = env_float("X_SIGNAL_MIN_UPSIDE_PCT_FOR_WEAK", 0.0)
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC = env_float("X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC", 8.0)
X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC = env_float("X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC", 12.0)
FOLLOWED_EQUITIES_PATH = env_str("FOLLOWED_EQUITIES_PATH", "followed_equities.json")
X_SIGNAL_USDC_MIN = env_float(
    "X_SIGNAL_EQUITY_MIN_TRADE",
    env_float("X_SIGNAL_USDC_MIN", env_float("AUTO_USDC_FOR_X_SIGNAL_MIN_USDC", 5.0)),
)
X_SIGNAL_WMATIC_MIN_VALUE = env_float(
    "X_SIGNAL_WMATIC_MIN_VALUE",
    env_float("AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE", 15.0),
)
AUTO_POPULATE_USDC_AMOUNT = env_float("AUTO_POPULATE_USDC_AMOUNT", 20.0)
AUTO_USDC_FOR_X_SIGNAL_MIN_USDC = env_float("AUTO_USDC_FOR_X_SIGNAL_MIN_USDC", X_SIGNAL_USDC_MIN)
AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE = env_float(
    "AUTO_USDC_FOR_X_SIGNAL_MIN_WMATIC_VALUE",
    X_SIGNAL_WMATIC_MIN_VALUE,
)
X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT = env_bool("X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT", True)
X_SIGNAL_USDC_SAFE_FLOOR = env_float("X_SIGNAL_USDC_SAFE_FLOOR", 20.0)
# When USDC is below safe floor, cap the Signal-Driven Rotation effective gate (aligns with ~$10 dynamic sizing).
X_SIGNAL_LIMITED_USDC_MIN_EFFECTIVE_GATE_USD = env_float(
    "X_SIGNAL_LIMITED_USDC_MIN_EFFECTIVE_GATE_USD", 10.0
)
# Signal-Driven Rotation effective-size tiers (after gas, USDC→equity BUY).
X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_BASE = env_float("X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_BASE", 12.0)
X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_MEDIUM_TIER = env_float(
    "X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_MEDIUM_TIER", 14.0
)
X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_WEAK_TIER = env_float(
    "X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_WEAK_TIER", 15.0
)
# PnL recovery: cap effective gate so ~$10 dynamic sizing is not blocked at $14+ tiers.
X_SIGNAL_RECOVERY_EFFECTIVE_GATE_ENABLED = env_bool("X_SIGNAL_RECOVERY_EFFECTIVE_GATE_ENABLED", True)
# Recovery cap (after gas); default $9 leaves headroom vs ~$10 sizing + gas while staying above $8 hard floor.
X_SIGNAL_RECOVERY_MIN_EFFECTIVE_GATE_USD = env_float("X_SIGNAL_RECOVERY_MIN_EFFECTIVE_GATE_USD", 9.0)
# Boost recovery BUY notional so effective_after_gas reliably clears the recovery cap.
X_SIGNAL_RECOVERY_GAS_BUFFER_USD = env_float("X_SIGNAL_RECOVERY_GAS_BUFFER_USD", 1.25)
# Relax when control.json max_copy_trade_pct is at/below this defensive tier (0 = env-only trigger).
X_SIGNAL_RECOVERY_MAX_COPY_PCT_THRESHOLD = env_float(
    "X_SIGNAL_RECOVERY_MAX_COPY_PCT_THRESHOLD", 0.06
)
# Relax when control.json stable_usd (USDT+USDC) is below this runway (aligns with moderate tier).
X_SIGNAL_RECOVERY_STABLE_USD_MAX = env_float("X_SIGNAL_RECOVERY_STABLE_USD_MAX", 100.0)
# Relax when session PnL (portfolio_history vs portfolio_session_baseline.json) is negative.
X_SIGNAL_RECOVERY_SESSION_PNL_ENABLED = env_bool("X_SIGNAL_RECOVERY_SESSION_PNL_ENABLED", True)
X_SIGNAL_AUTO_USDC_TARGET = env_float("X_SIGNAL_AUTO_USDC_TARGET", 25.0)
X_SIGNAL_AUTO_USDC_TOPUP_ENABLED = env_bool("X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", True)
X_SIGNAL_AUTO_USDC_MIN_SWAP_USD = env_float("X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", 8.0)
X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS = env_int("X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS", 180)
X_SIGNAL_EQUITY_TRADE_PCT = env_float("X_SIGNAL_EQUITY_TRADE_PCT", 0.18)
X_SIGNAL_EQUITY_MAX_TRADE = env_float("X_SIGNAL_EQUITY_MAX_TRADE", 28.0)
X_SIGNAL_EQUITY_COOLDOWN_SECONDS = env_int(
    "X_SIGNAL_EQUITY_COOLDOWN_SECONDS",
    PER_ASSET_COOLDOWN_SECONDS,
)
X_SIGNAL_EQUITY_STRONG_TP_PCT = env_float("X_SIGNAL_EQUITY_STRONG_TP_PCT", 12.0)
# Optional per-symbol skip (balance-read workaround). Empty = trade all followed_equities assets.
X_SIGNAL_TEMP_SKIP_SYMBOLS = env_symbol_frozenset("X_SIGNAL_TEMP_SKIP_SYMBOLS", "")
# When true, .xsignal_blocked_symbols is never bypassed when it would remove all followed assets
# (default false preserves legacy "ignoring blocks this cycle" WARNING for X-SIGNAL equity only).
X_SIGNAL_HONOR_FULL_BLOCKLIST = env_bool("X_SIGNAL_HONOR_FULL_BLOCKLIST", False)
# TEMPORARY (May 2026): WBTC_* BUY min notional while Polygon WBTC liquidity is poor; 0 disables.
# Lowered 25.0 -> 10.0 (May 2026): typical X-SIGNAL dynamic sizing on a sub-$30 USDC bankroll
# is ~$10.25-$10.30, so a $25 floor blocked WBTC_ALPHA 100% of the time even at signal=0.83.
# At ~$10 notional with the high-conviction slippage tier and the swap-executor's effective
# min trade guard, fills are gated by realized-slippage ceiling rather than an arbitrary floor.
# Operators on thinner liquidity windows can dial it back up via env without code changes.
X_SIGNAL_WBTC_MIN_NOTIONAL_USD = env_float("X_SIGNAL_WBTC_MIN_NOTIONAL_USD", 10.0)
X_SIGNAL_EQUITY_SELL_FRACTION = env_float("X_SIGNAL_EQUITY_SELL_FRACTION", 0.55)
# REVERSIBLE travel tune (2026-05-09): X-SIGNAL-only dust/exec floor when combined stables ≥ ~$80 (see swap_executor + signal_equity_trader).
X_SIGNAL_EQUITY_DUST_MIN_USD = env_float("X_SIGNAL_EQUITY_DUST_MIN_USD", 7.5)
CHAIN_HINT_WRONG_ETH_ADDRESSES = env_str("CHAIN_HINT_WRONG_ETH_ADDRESSES", "")
X_SIGNAL_DYNAMIC_TIER_HIGH_MIN = env_float("X_SIGNAL_DYNAMIC_TIER_HIGH_MIN", 0.90)
X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH = env_float("X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH", 20.0)
X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE = env_float("X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE", 15.0)
X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE = env_float("X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE", 12.0)

SWAP_SLIPPAGE_BPS = env_int("SWAP_SLIPPAGE_BPS", 100)
# Read-only inventory mark-to-USDT for FE_USD (followed equities). Looser than live swap slippage.
INVENTORY_MTM_SLIPPAGE_BPS = env_int("INVENTORY_MTM_SLIPPAGE_BPS", 300)
# Max upward drift per day for persisted FE_USD last-good spot (live quote required to raise cache).
FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY = env_float("FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY", 5.0)
# When cached floor exceeds live spot within band, refresh cache down (Agent H).
FE_USD_FALLBACK_REFRESH_ENABLED = env_bool("FE_USD_FALLBACK_REFRESH_ENABLED", True)
FE_USD_FALLBACK_MAX_STALE_PCT = env_float("FE_USD_FALLBACK_MAX_STALE_PCT", 5.0)
FE_USD_FALLBACK_MIN_LIVE_USD = env_float("FE_USD_FALLBACK_MIN_LIVE_USD", 1.0)
FALLBACK_ROUTER_SLIPPAGE_BPS_RAW = env_str("FALLBACK_ROUTER_SLIPPAGE_BPS", "")
FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS_RAW = env_str("FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS", "")
ONCHAIN_SWAP_RETRY_EXTRA_BPS = env_int("ONCHAIN_SWAP_RETRY_EXTRA_BPS", 50)
ONEINCH_SWAP_ENDPOINT = env_str("ONEINCH_SWAP_ENDPOINT", "https://api.1inch.dev/swap/v5.2/137/swap")
ONEINCH_SPENDER_ENDPOINT = env_str(
    "ONEINCH_SPENDER_ENDPOINT",
    "https://api.1inch.dev/swap/v5.2/137/approve/spender",
)
ONEINCH_API_KEY = env_str("ONEINCH_API_KEY", env_str("INCH_API_KEY", ""))
FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS = 600
HIGH_CONVICTION_FALLBACK_PRIMARY_BPS = env_int(
    "HIGH_CONVICTION_FALLBACK_PRIMARY_BPS",
    env_int("HIGH_CONVICTION_FALLBACK_SLIPPAGE_BPS", 4000),
)
HIGH_CONVICTION_FALLBACK_RETRY_BPS = env_int(
    "HIGH_CONVICTION_FALLBACK_RETRY_BPS",
    env_int("HIGH_CONVICTION_FALLBACK_RETRY_SLIPPAGE_BPS", 5000),
)
# Small high-conviction X-SIGNAL (USDC_TO_EQUITY, |signal|>=0.85, notional<=$12) fallback router only.
# Tightened 8000/10000 -> 3000/5000 bps (May 2026): the V3 pre-flight `check=ok` gate already
# validates the live quote, and 100% fill rate at 8000 bps showed actual realized slippage was
# nowhere near 80%. Cuts worst-case loss-per-trade by ~50% (~$8 -> ~$3 on a $10 trade) while
# preserving a 5x safety margin over typical V3 fills (<1%). Operators can revert via env if
# pool liquidity for a specific pair degrades.
X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_PRIMARY_BPS = env_int(
    "X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_PRIMARY_BPS",
    3000,
)
X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_RETRY_BPS = env_int(
    "X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_RETRY_BPS",
    5000,
)
# ~$10 gated trades: use small-tier execution (8000/10000, 50 min_out) when |signal| >= this at/below max notional.
X_SIGNAL_SMALL_GATED_MIN_STRENGTH = env_float("X_SIGNAL_SMALL_GATED_MIN_STRENGTH", 0.80)
X_SIGNAL_SMALL_GATED_MAX_NOTIONAL_USD = env_float("X_SIGNAL_SMALL_GATED_MAX_NOTIONAL_USD", 12.0)
# Signal-driven execution quality (May 2026): X-SIGNAL USDC→equity gated BUY — fallback router only.
X_SIGNAL_GATED_TRADE_FALLBACK_PRIMARY_BPS = env_int(
    "X_SIGNAL_GATED_TRADE_FALLBACK_PRIMARY_BPS",
    9500,
)
X_SIGNAL_GATED_TRADE_FALLBACK_RETRY_BPS = env_int(
    "X_SIGNAL_GATED_TRADE_FALLBACK_RETRY_BPS",
    12500,
)
# Extra min_out haircut beyond quoted slippage (bps) for gated X-SIGNAL fallback swaps.
X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS = env_int(
    "X_SIGNAL_GATED_TRADE_MIN_OUT_EXTRA_BPS",
    100,
)
# Additional min_out buffer (bps) when |signal| >= 0.90 on gated/small high-conviction paths.
X_SIGNAL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS = env_int(
    "X_SIGNAL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS",
    25,
)
X_SIGNAL_SMALL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS = env_int(
    "X_SIGNAL_SMALL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS",
    50,
)
# Pause per-asset X-SIGNAL BUY after repeated on-chain STF (slippage) reverts.
X_SIGNAL_STF_PAUSE_AFTER_FAILURES = env_int("X_SIGNAL_STF_PAUSE_AFTER_FAILURES", 2)
X_SIGNAL_STF_PAUSE_SECONDS = env_int("X_SIGNAL_STF_PAUSE_SECONDS", 3600)
# Multiply long STF pause duration per asset on each repeated pause cycle (cap: X_SIGNAL_STF_MAX_PAUSE_SECONDS).
X_SIGNAL_STF_PAUSE_ESCALATION_MULTIPLIER = env_float("X_SIGNAL_STF_PAUSE_ESCALATION_MULTIPLIER", 2.0)
X_SIGNAL_STF_MAX_PAUSE_SECONDS = env_int("X_SIGNAL_STF_MAX_PAUSE_SECONDS", 14400)
# Short per-asset cooldown after each STF revert (before long pause at STF_PAUSE_AFTER_FAILURES).
X_SIGNAL_STF_FAILURE_COOLDOWN_SECONDS = env_int("X_SIGNAL_STF_FAILURE_COOLDOWN_SECONDS", 600)
# Pre-flight: re-quote if cached V3 quote is older than this many seconds before submit.
X_SIGNAL_PREFLIGHT_MAX_QUOTE_AGE_SECONDS = env_float("X_SIGNAL_PREFLIGHT_MAX_QUOTE_AGE_SECONDS", 8.0)
# Pre-flight: abort when eth_estimateGas exceeds this limit (illiquid / bad path).
X_SIGNAL_PREFLIGHT_MAX_GAS_LIMIT = env_int("X_SIGNAL_PREFLIGHT_MAX_GAS_LIMIT", 650000)
# High-conviction (|signal|>=0.90): lower first ramp step vs tier max — ramp still reaches retry bps.
X_SIGNAL_HIGH_CONVICTION_PRIMARY_RELIEF_BPS = env_int("X_SIGNAL_HIGH_CONVICTION_PRIMARY_RELIEF_BPS", 800)
# Seconds to wait before re-quoting on X-SIGNAL fallback retry (fresh pool state).
X_SIGNAL_FALLBACK_REQUOTE_DELAY_SECONDS = env_float("X_SIGNAL_FALLBACK_REQUOTE_DELAY_SECONDS", 1.5)
# Prefer 0.3% V3 pool when its quote is within this many bps of the best tier (stabler path for equities).
X_SIGNAL_STABLE_FEE_PREFER_BPS = env_int("X_SIGNAL_STABLE_FEE_PREFER_BPS", 75)
# X-SIGNAL quoting: try QuoterV2 before legacy QuoterV1 (Polygon); fallback to V2 router when V3 pools missing.
X_SIGNAL_QUOTE_PREFER_QUOTER_V2 = env_bool("X_SIGNAL_QUOTE_PREFER_QUOTER_V2", True)
X_SIGNAL_V2_ROUTER_FALLBACK_ENABLED = env_bool("X_SIGNAL_V2_ROUTER_FALLBACK_ENABLED", True)
# Small USDC→equity trades (raw 6-dec amount): probe 0.3% fee tier before 0.05%/1%.
X_SIGNAL_SMALL_TRADE_USDC_RAW = env_int("X_SIGNAL_SMALL_TRADE_USDC_RAW", 15_000_000)
# Fallback slippage for USDC→equity X-SIGNAL that missed gated/small tiers (still ramps on router).
X_SIGNAL_DEFAULT_FALLBACK_PRIMARY_BPS = env_int("X_SIGNAL_DEFAULT_FALLBACK_PRIMARY_BPS", 7000)
X_SIGNAL_DEFAULT_FALLBACK_RETRY_BPS = env_int("X_SIGNAL_DEFAULT_FALLBACK_RETRY_BPS", 11000)
X_SIGNAL_DEFAULT_MIN_OUT_EXTRA_BPS = env_int("X_SIGNAL_DEFAULT_MIN_OUT_EXTRA_BPS", 75)

MAIN_STRATEGY_MIN_USDT_RESERVE = env_float("MAIN_STRATEGY_MIN_USDT_RESERVE", 25.0)
MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD = env_float("MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD", 52.0)
MAIN_STRATEGY_CUT_LOSS_WMATIC_USD = env_float("MAIN_STRATEGY_CUT_LOSS_WMATIC_USD", 40.0)
MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE = env_float("MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE", 50.0)
MAIN_STRATEGY_RESERVE_SELL_FRACTION = env_float("MAIN_STRATEGY_RESERVE_SELL_FRACTION", 0.45)
MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION = env_float("MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION", 0.28)
# Anti-churn: skip USDT→WMATIC for N cycles after a WMATIC→stable exit; skip when stack ≥ cap USD.
# TEMPORARY PnL recovery (May 2026): defaults tightened vs 6 / 22 — revert when portfolio stabilizes.
MAIN_STRATEGY_ACCUMULATE_COOLDOWN_CYCLES = env_int("MAIN_STRATEGY_ACCUMULATE_COOLDOWN_CYCLES", 8)
MAIN_STRATEGY_ACCUMULATE_MAX_WMATIC_USD = env_float("MAIN_STRATEGY_ACCUMULATE_MAX_WMATIC_USD", 18.0)
# TEMPORARY PnL recovery (May 2026): pause sub-$5 idle micro-rotations; tighten accumulate defaults above.
MAIN_STRATEGY_PNL_RECOVERY_MODE = env_bool("MAIN_STRATEGY_PNL_RECOVERY_MODE", True)
MAIN_STRATEGY_PNL_RECOVERY_IDLE_MIN_NOTIONAL_USD = env_float(
    "MAIN_STRATEGY_PNL_RECOVERY_IDLE_MIN_NOTIONAL_USD", 8.0
)
# Recovery: minimum notional for long-idle micro / force-small P2 paths (replaces $1.35 floor).
MAIN_STRATEGY_PNL_RECOVERY_ROTATION_MIN_NOTIONAL_USD = env_float(
    "MAIN_STRATEGY_PNL_RECOVERY_ROTATION_MIN_NOTIONAL_USD", 8.0
)
# Recovery: extra idle cycles before low-stack / long-idle micro rotations.
MAIN_STRATEGY_PNL_RECOVERY_LONG_IDLE_CYCLE_BONUS = env_int(
    "MAIN_STRATEGY_PNL_RECOVERY_LONG_IDLE_CYCLE_BONUS", 3
)
# Recovery strictness also when control.json max_copy_trade_pct is at/below this tier (0 = env-only).
MAIN_STRATEGY_RECOVERY_MAX_COPY_PCT_THRESHOLD = env_float(
    "MAIN_STRATEGY_RECOVERY_MAX_COPY_PCT_THRESHOLD", 0.06
)
# Optional operator alias; X-SIGNAL recovery gate also honors this when set true independently.
PNL_RECOVERY_MODE = env_bool("PNL_RECOVERY_MODE", False)
# Rotation / gas-protection (modules.swap_executor — P2, force, idle, dust defer, mild-loss)
MAIN_STRATEGY_ROTATION_MIN_NOTIONAL_USD = env_float("MAIN_STRATEGY_ROTATION_MIN_NOTIONAL_USD", 8.0)
MAIN_STRATEGY_LOW_ROTATION_MIN_NOTIONAL_USD = env_float("MAIN_STRATEGY_LOW_ROTATION_MIN_NOTIONAL_USD", 10.0)
MAIN_STRATEGY_MODERATE_ROTATION_MIN_NOTIONAL_USD = env_float(
    "MAIN_STRATEGY_MODERATE_ROTATION_MIN_NOTIONAL_USD", 10.0
)
MAIN_STRATEGY_LONG_IDLE_NOTIONAL_FLOOR_USD = env_float(
    "MAIN_STRATEGY_LONG_IDLE_NOTIONAL_FLOOR_USD", 1.35
)
MAIN_STRATEGY_P2_WM_MIN_USD = env_float("MAIN_STRATEGY_P2_WM_MIN_USD", 7.0)
MAIN_STRATEGY_P2_SIGNAL_MIN = env_float("MAIN_STRATEGY_P2_SIGNAL_MIN", 0.55)
MAIN_STRATEGY_FORCE_WM_MIN_USD = env_float("MAIN_STRATEGY_FORCE_WM_MIN_USD", 5.5)
MAIN_STRATEGY_FORCE_CYCLES_MIN = env_int("MAIN_STRATEGY_FORCE_CYCLES_MIN", 4)
MAIN_STRATEGY_FORCE_NOTIONAL_FLOOR_USD = env_float(
    "MAIN_STRATEGY_FORCE_NOTIONAL_FLOOR_USD", 8.0
)
MAIN_STRATEGY_LOW_WM_USD_THRESHOLD = env_float("MAIN_STRATEGY_LOW_WM_USD_THRESHOLD", 7.0)
MAIN_STRATEGY_MODERATE_WM_USD_THRESHOLD = env_float("MAIN_STRATEGY_MODERATE_WM_USD_THRESHOLD", 15.0)
MAIN_STRATEGY_LOW_P2_WM_MIN_USD = env_float("MAIN_STRATEGY_LOW_P2_WM_MIN_USD", 5.0)
MAIN_STRATEGY_LOW_P2_SIGNAL_MIN = env_float("MAIN_STRATEGY_LOW_P2_SIGNAL_MIN", 0.45)
MAIN_STRATEGY_LOW_FORCE_WM_MIN_USD = env_float("MAIN_STRATEGY_LOW_FORCE_WM_MIN_USD", 5.0)
MAIN_STRATEGY_LOW_FORCE_CYCLES_MIN = env_int("MAIN_STRATEGY_LOW_FORCE_CYCLES_MIN", 5)
MAIN_STRATEGY_MODERATE_P2_WM_MIN_USD = env_float("MAIN_STRATEGY_MODERATE_P2_WM_MIN_USD", 12.0)
MAIN_STRATEGY_MODERATE_P2_SIGNAL_MIN = env_float("MAIN_STRATEGY_MODERATE_P2_SIGNAL_MIN", 0.50)
MAIN_STRATEGY_MODERATE_FORCE_WM_MIN_USD = env_float("MAIN_STRATEGY_MODERATE_FORCE_WM_MIN_USD", 12.0)
MAIN_STRATEGY_MODERATE_FORCE_CYCLES_MIN = env_int("MAIN_STRATEGY_MODERATE_FORCE_CYCLES_MIN", 5)
MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD = env_float("MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD", 8.0)
# Low-stables exception: allow sub-$8 WMATIC→stable main exits to rebuild buffer (reversible).
MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_ENABLED = env_bool(
    "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_ENABLED", True
)
MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD = env_float(
    "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD", 15.0
)
MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MIN_PORTFOLIO_USD = env_float(
    "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MIN_PORTFOLIO_USD", 130.0
)
MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_NOTIONAL_FLOOR_USD = env_float(
    "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_NOTIONAL_FLOOR_USD", 4.0
)
MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_CYCLE_COOLDOWN = env_int(
    "MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_CYCLE_COOLDOWN", 3
)
# When USDT reserve protection / low-stables rebuild sells WMATIC, prefer USDC if combined stables are critical.
MAIN_STRATEGY_RESERVE_PREFER_USDC = env_bool("MAIN_STRATEGY_RESERVE_PREFER_USDC", True)
# FE-heavy + low stables (WMATIC=0): partial EQUITY→USDC trim before USDC→EQUITY BUY (Cleanup #6).
FE_STABLE_RUNWAY_ENABLED = env_bool("FE_STABLE_RUNWAY_ENABLED", True)
FE_STABLE_RUNWAY_MIN_FE_SHARE = env_float("FE_STABLE_RUNWAY_MIN_FE_SHARE", 0.55)
FE_STABLE_RUNWAY_TARGET_STABLE_USD = env_float("FE_STABLE_RUNWAY_TARGET_STABLE_USD", 40.0)
# Tiered runway: allow one capped USDC→EQUITY BUY when stables ≥ reserve but < target (79% FE band).
FE_STABLE_RUNWAY_TIERED_ENABLED = env_bool("FE_STABLE_RUNWAY_TIERED_ENABLED", True)
FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL = env_float("FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL", 0.85)
FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD = env_float("FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD", 10.0)
# After tiered BUY, stables must stay ≥ reserve floor + this headroom (blocks $19→$10→$9 ping-pong).
FE_STABLE_RUNWAY_TIERED_RESERVE_HEADROOM_USD = env_float(
    "FE_STABLE_RUNWAY_TIERED_RESERVE_HEADROOM_USD", 2.0
)
# Minimum effective tiered notional; below this the bypass is skipped (defer to rebuild).
FE_STABLE_RUNWAY_TIERED_MIN_NOTIONAL_USD = env_float("FE_STABLE_RUNWAY_TIERED_MIN_NOTIONAL_USD", 5.0)
# High-FE de-risk: capped WETH→USDC trim in stables dead zone (≥ reserve, < target, WMATIC dust).
FE_STABLE_RUNWAY_DERISK_ENABLED = env_bool("FE_STABLE_RUNWAY_DERISK_ENABLED", True)
FE_STABLE_RUNWAY_DERISK_MIN_FE_SHARE = env_float("FE_STABLE_RUNWAY_DERISK_MIN_FE_SHARE", 0.80)
FE_STABLE_RUNWAY_DERISK_MIN_STABLE_USD = env_float("FE_STABLE_RUNWAY_DERISK_MIN_STABLE_USD", 15.0)
FE_STABLE_RUNWAY_DERISK_MAX_TRIM_NOTIONAL_USD = env_float(
    "FE_STABLE_RUNWAY_DERISK_MAX_TRIM_NOTIONAL_USD", 12.0
)
# Skip de-risk when WMATIC USD ≥ this (main-strategy rebuild still actionable).
FE_STABLE_RUNWAY_DERISK_MAX_WMATIC_USD = env_float("FE_STABLE_RUNWAY_DERISK_MAX_WMATIC_USD", 8.0)
# Operating reserve: keep stables ≥ seed × pct for gas + RPC/hosting (defer new entries only).
OPERATING_RESERVE_ENABLED = env_bool("OPERATING_RESERVE_ENABLED", True)
OPERATING_RESERVE_PCT = env_float("OPERATING_RESERVE_PCT", 10.0)
# Tiered X-SIGNAL only when stables ≥ reserve floor (default off — do not buy below reserve).
OPERATING_RESERVE_TIERED_EXEMPT_ENABLED = env_bool("OPERATING_RESERVE_TIERED_EXEMPT_ENABLED", False)
# Stage seed for reserve floor; 0 = use current TOTAL at cycle time.
STAGE_SEED_USD = env_float("STAGE_SEED_USD", 0.0)
# Optional: scale reserve seed from portfolio_history TOTAL EMA (max with STAGE_SEED_USD).
STAGE_SEED_AUTO_SYNC_ENABLED = env_bool("STAGE_SEED_AUTO_SYNC_ENABLED", True)
STAGE_SEED_AUTO_SYNC_EMA_DAYS = env_int("STAGE_SEED_AUTO_SYNC_EMA_DAYS", 7)
STAGE_SEED_AUTO_SYNC_MIN_USD = env_float("STAGE_SEED_AUTO_SYNC_MIN_USD", 50.0)
# Wallet opex runway alert (scripts/opex_runway.py; operator pays Ankr from stage wallet).
OPEX_MONTHLY_USD = env_float("OPEX_MONTHLY_USD", 10.0)
OPEX_CURSOR_MONTHLY_USD = env_float("OPEX_CURSOR_MONTHLY_USD", 0.0)
OPEX_GROK_MONTHLY_USD = env_float("OPEX_GROK_MONTHLY_USD", 0.0)
OPEX_HOSTING_MONTHLY_USD = env_float("OPEX_HOSTING_MONTHLY_USD", 0.0)
OPEX_RUNWAY_ALERT_DAYS = env_int("OPEX_RUNWAY_ALERT_DAYS", 14)
OPEX_RUNWAY_TELEGRAM_ENABLED = env_bool("OPEX_RUNWAY_TELEGRAM_ENABLED", False)
OPEX_RUNWAY_AUTO_CHECK_ENABLED = env_bool("OPEX_RUNWAY_AUTO_CHECK_ENABLED", True)
OPEX_RUNWAY_AUTO_CHECK_INTERVAL_HOURS = env_float("OPEX_RUNWAY_AUTO_CHECK_INTERVAL_HOURS", 6.0)
# External layer: portfolio-driven auto pause/unpause (writes control.json every ~30s).
EXTERNAL_AUTO_PAUSE_ENABLED = env_bool("EXTERNAL_AUTO_PAUSE_ENABLED", False)
EXTERNAL_RPC_PAUSE_ENABLED = env_bool("EXTERNAL_RPC_PAUSE_ENABLED", False)
EXTERNAL_AUTO_GREEN_HOURS = env_float("EXTERNAL_AUTO_GREEN_HOURS", 12.0)
EXTERNAL_AUTO_SESSION_MIN_PCT = env_float("EXTERNAL_AUTO_SESSION_MIN_PCT", -1.0)
EXTERNAL_AUTO_WINDOW_MIN_PCT = env_float("EXTERNAL_AUTO_WINDOW_MIN_PCT", -2.0)
REDUCED_HIGH_RISK_MIN_TRADE_USD = env_float("REDUCED_HIGH_RISK_MIN_TRADE_USD", 8.0)
# HIGH-risk loss-cut: trim underwater X-SIGNAL equity (default LINK_ALPHA); block BUYs while underwater.
ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL = env_bool("ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL", True)
HIGH_RISK_LOSS_CUT_MIN_PORTFOLIO_USD = env_float("HIGH_RISK_LOSS_CUT_MIN_PORTFOLIO_USD", 130.0)
HIGH_RISK_LOSS_CUT_LOSS_PCT = env_float("HIGH_RISK_LOSS_CUT_LOSS_PCT", 3.0)
HIGH_RISK_LOSS_CUT_SYMBOLS = env_symbol_frozenset("HIGH_RISK_LOSS_CUT_SYMBOLS", "LINK_ALPHA")
HIGH_RISK_LOSS_CUT_SELL_FRACTION = env_float("HIGH_RISK_LOSS_CUT_SELL_FRACTION", 0.55)
HIGH_RISK_LOSS_CUT_BLOCK_BUYS = env_bool("HIGH_RISK_LOSS_CUT_BLOCK_BUYS", True)
# When no persisted entry yet, estimate cost above FE floor (prior LINK buys were above fallback).
HIGH_RISK_LOSS_CUT_BOOTSTRAP_ENTRY_PREMIUM_PCT = env_float(
    "HIGH_RISK_LOSS_CUT_BOOTSTRAP_ENTRY_PREMIUM_PCT", 12.0
)
# Allow loss-cut trim when underwater even if buffer risk is LOW/MEDIUM (BUY block still applies in-loop).
HIGH_RISK_LOSS_CUT_WHEN_UNDERWATER_ANY_RISK = env_bool(
    "HIGH_RISK_LOSS_CUT_WHEN_UNDERWATER_ANY_RISK", True
)
# Cap loss-cut live spot when on-chain quote exceeds fallback × this factor (drained-pool misquote).
HIGH_RISK_LOSS_CUT_SPOT_SANITY_MULT = env_float("HIGH_RISK_LOSS_CUT_SPOT_SANITY_MULT", 1.35)
# Skip loss-cut when position or partial-sell notional is below this (avoids STF/gas on dust).
HIGH_RISK_LOSS_CUT_MIN_EQUITY_USD = env_float(
    "HIGH_RISK_LOSS_CUT_MIN_EQUITY_USD",
    env_float("MIN_TRADE_USD", 10.0),
)
MAIN_STRATEGY_LONG_IDLE_CYCLES_LOW = env_int("MAIN_STRATEGY_LONG_IDLE_CYCLES_LOW", 3)
MAIN_STRATEGY_LONG_IDLE_CYCLES_MODERATE = env_int("MAIN_STRATEGY_LONG_IDLE_CYCLES_MODERATE", 6)
MAIN_STRATEGY_LONG_IDLE_CYCLES_HEALTHY = env_int("MAIN_STRATEGY_LONG_IDLE_CYCLES_HEALTHY", 8)
MAIN_STRATEGY_LONG_IDLE_FORCE_WM_MIN_USD = env_float("MAIN_STRATEGY_LONG_IDLE_FORCE_WM_MIN_USD", 1.5)
MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_LOW = env_float(
    "MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_LOW", 0.35
)
MAIN_STRATEGY_IDLE_ROTATION_NOTIONAL_FLOOR_LOW = env_float(
    "MAIN_STRATEGY_IDLE_ROTATION_NOTIONAL_FLOOR_LOW", 1.35
)
MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_HEALTHY = env_float(
    "MAIN_STRATEGY_IDLE_ROTATION_SELL_FRACTION_HEALTHY", 0.28
)
MAIN_STRATEGY_MILD_LOSS_ENABLED = env_bool("MAIN_STRATEGY_MILD_LOSS_ENABLED", True)
MAIN_STRATEGY_MILD_LOSS_MAX_NOTIONAL_USD = env_float("MAIN_STRATEGY_MILD_LOSS_MAX_NOTIONAL_USD", 8.0)
MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MIN_PCT = env_float("MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MIN_PCT", -7.0)
MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MAX_PCT = env_float("MAIN_STRATEGY_MILD_LOSS_IDLE_GAIN_MAX_PCT", -1.0)
MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MIN_USD = env_float("MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MIN_USD", 5.0)
MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MAX_USD = env_float("MAIN_STRATEGY_MILD_LOSS_IDLE_WM_MAX_USD", 10.0)
MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN = env_int("MAIN_STRATEGY_MILD_LOSS_IDLE_CYCLES_MIN", 1)
MAIN_STRATEGY_MILD_LOSS_FAST_WM_MIN_QTY = env_float("MAIN_STRATEGY_MILD_LOSS_FAST_WM_MIN_QTY", 10.0)
COPY_TRADE_AGGRESSIVE_THRESHOLD = env_float("COPY_TRADE_AGGRESSIVE_THRESHOLD", 0.20)
COPY_BASE_EXPECTED_EDGE_PCT = env_float("COPY_BASE_EXPECTED_EDGE_PCT", 6.0)
COPY_GAS_EDGE_MULTIPLIER = env_float("COPY_GAS_EDGE_MULTIPLIER", 2.5)
COPY_MIN_EFFECTIVE_TRADE_AFTER_GAS_USD = env_float("COPY_MIN_EFFECTIVE_TRADE_AFTER_GAS_USD", 10.0)
COPY_MIN_MARGINAL_TRADE_USD = env_float("COPY_MIN_MARGINAL_TRADE_USD", 12.0)
COPY_WALLET_PERFORMANCE_FILE = env_str("COPY_WALLET_PERFORMANCE_FILE", "wallet_performance.json")
COPY_WALLET_PERFORMANCE_WINDOW_TRADES = env_int("COPY_WALLET_PERFORMANCE_WINDOW_TRADES", 25)
COPY_WALLET_PERFORMANCE_MIN_TRADES = env_int("COPY_WALLET_PERFORMANCE_MIN_TRADES", 8)
COPY_WALLET_PERFORMANCE_POOR_WINRATE = env_float("COPY_WALLET_PERFORMANCE_POOR_WINRATE", 0.40)
COPY_WALLET_PERFORMANCE_POOR_AVG_PNL_USD = env_float("COPY_WALLET_PERFORMANCE_POOR_AVG_PNL_USD", -0.20)
COPY_WALLET_PERFORMANCE_PENALTY_MULTIPLIER = env_float("COPY_WALLET_PERFORMANCE_PENALTY_MULTIPLIER", 0.65)

PROTECTION_MAX_DAILY_LOSS_PCT = env_int("PROTECTION_MAX_DAILY_LOSS_PCT", 15)
PROTECTION_MIN_POL_BALANCE = env_float("PROTECTION_MIN_POL_BALANCE", 2.0)
PROTECTION_MAX_TRADE_SIZE_USD = env_float("PROTECTION_MAX_TRADE_SIZE_USD", 35.0)
PROTECTION_GAS_MULTIPLIER = env_float("PROTECTION_GAS_MULTIPLIER", 1.25)
PROTECTION_FLUCTUATION_USDT_THRESHOLD = env_float("PROTECTION_FLUCTUATION_USDT_THRESHOLD", 30.0)
PROTECTION_FLUCTUATION_MIN_WMATIC = env_float("PROTECTION_FLUCTUATION_MIN_WMATIC", 50.0)
PROTECTION_FLUCTUATION_SELL_FRACTION = env_float("PROTECTION_FLUCTUATION_SELL_FRACTION", 0.25)
PROTECTION_FLUCTUATION_COOLDOWN_SECONDS = env_int("PROTECTION_FLUCTUATION_COOLDOWN_SECONDS", 1800)
PROTECTION_FLUCTUATION_MIN_SELL_USD = env_float("PROTECTION_FLUCTUATION_MIN_SELL_USD", 8.0)
PROTECTION_PROFIT_LOCK_PERCENT = env_float("PROTECTION_PROFIT_LOCK_PERCENT", 8.0)

NANOCLAW_AGENT_LAYER_ENABLED = env_bool("NANOCLAW_AGENT_LAYER_ENABLED", False)
NANOCLAW_TELEMETRY_TELEGRAM = env_bool("NANOCLAW_TELEMETRY_TELEGRAM", False)
NANOCLAW_AGENT_CAN_OVERRIDE_SWAP = env_bool("NANOCLAW_AGENT_CAN_OVERRIDE_SWAP", False)
NANOCLAW_AGENT_LAYER_ADVISORY = env_bool("NANOCLAW_AGENT_LAYER_ADVISORY", False)
NANOCLAW_GROK_ENABLED = env_bool("NANOCLAW_GROK_ENABLED", False)
GROK_API_KEY = env_str("GROK_API_KEY", env_str("XAI_API_KEY", ""))
GROK_API_BASE = env_str("GROK_API_BASE", "https://api.x.ai/v1")
GROK_MODEL = env_str("GROK_MODEL", "grok-2-latest")
TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = env_str("TELEGRAM_CHAT_ID", "")
NANOCLAW_TRADE_ATTRIBUTION = env_bool("NANOCLAW_TRADE_ATTRIBUTION", True)

PORTFOLIO_BASELINE_USD_RAW = env_str("PORTFOLIO_BASELINE_USD", "")

GOOGLON = env_str("GOOGLON", "")
MSFTON = env_str("MSFTON", "")
APPLON = env_str("APPLON", "")
AMZNON = env_str("AMZNON", "")


def parse_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:
        return float(default)


def get_resolved_key() -> str:
    return resolve_private_key(require=False)[0]


class MissingPrivateKeyError(RuntimeError):
    """Raised when no supported private key source is available."""


_PRIVATE_KEY_LOGGED_SOURCE: str | None = None

_HEX_NIBBLE = frozenset("0123456789abcdefABCDEF")


def normalize_private_key_hex(key: str) -> str:
    """Strip `.env` / editor cruft and normalize secp256k1 hex keys for `eth_account`.

    - Trims ASCII whitespace (including stray newlines that make `from_key` see 33 bytes).
    - Strips a leading UTF-8 BOM if present.
    - If the payload is exactly 64 hex digits, prefixes ``0x`` (some operators paste hex without it).
    - If every character is hex but length is not 64, raises ``ValueError`` (e.g. 66 nibbles → 33-byte error at signing).
    """
    k = (key or "").strip()
    if k.startswith("\ufeff"):
        k = k.lstrip("\ufeff").strip()
    if not k:
        return k
    if k.lower().startswith("0x"):
        body = k[2:].strip()
    else:
        body = k
    if not body:
        return k
    if all(ch in _HEX_NIBBLE for ch in body):
        if len(body) == 64:
            return "0x" + body.lower()
        raise ValueError(
            "POLYGON_PRIVATE_KEY hex has length %d nibbles (expected 64). "
            "Use one line in .env: 0x + 64 hex (or 64 hex only); remove quotes, NULs, and stray characters."
            % len(body)
        )
    return k


def _resolve_private_key_from_env() -> tuple[str, str]:
    env_polygon_key = env_str("POLYGON_PRIVATE_KEY", "")
    if env_polygon_key:
        return env_polygon_key, "POLYGON_PRIVATE_KEY"
    env_legacy_key = env_str("PRIVATE_KEY", "")
    if env_legacy_key:
        return env_legacy_key, "PRIVATE_KEY"
    return "", "missing"


def resolve_private_key(
    private_key_param: str | None = None,
    *,
    require: bool = False,
    log_success: bool = False,
) -> tuple[str, str]:
    """
    Resolve signer key with a single shared precedence:
    1) POLYGON_PRIVATE_KEY
    2) PRIVATE_KEY (legacy)
    3) explicit function argument fallback (legacy call compatibility)
    Raises when ``require=True`` and no source resolves a key.
    """
    global _PRIVATE_KEY_LOGGED_SOURCE
    resolved_key, source = _resolve_private_key_from_env()
    if not resolved_key:
        arg_key = str(private_key_param or "").strip()
        if arg_key:
            resolved_key, source = arg_key, "function_arg"
    if require and not resolved_key:
        raise MissingPrivateKeyError(
            "Missing private key. Set POLYGON_PRIVATE_KEY (preferred) or PRIVATE_KEY in your .env, or pass private_key explicitly."
        )
    if log_success and resolved_key and _PRIVATE_KEY_LOGGED_SOURCE != source:
        print(f"[nanoclaw] Private key loaded from {source}")
        _PRIVATE_KEY_LOGGED_SOURCE = source
    if resolved_key:
        resolved_key = normalize_private_key_hex(resolved_key)
    return resolved_key, source
