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
PER_ASSET_COOLDOWN_MINUTES = env_int("PER_ASSET_COOLDOWN_MINUTES", 30)
PER_ASSET_COOLDOWN_SECONDS = PER_ASSET_COOLDOWN_MINUTES * 60
PER_WALLET_COOLDOWN = env_int("PER_WALLET_COOLDOWN", 180)
COPY_TRADING_ENABLED = env_bool("COPY_TRADING_ENABLED", True)

POL_USD_PRICE = env_float("POL_USD_PRICE", 0.10)
MIN_POL_FOR_GAS = env_float("MIN_POL_FOR_GAS", 0.005)
AUTO_TOPUP_POL = env_bool("AUTO_TOPUP_POL", True)
POL_TOPUP_AMOUNT = env_float("POL_TOPUP_AMOUNT", 0.03)
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
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = env_float(
    "X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD",
    X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
)
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

MAIN_STRATEGY_MIN_USDT_RESERVE = env_float("MAIN_STRATEGY_MIN_USDT_RESERVE", 25.0)
MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD = env_float("MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD", 52.0)
MAIN_STRATEGY_CUT_LOSS_WMATIC_USD = env_float("MAIN_STRATEGY_CUT_LOSS_WMATIC_USD", 40.0)
MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE = env_float("MAIN_STRATEGY_CUT_LOSS_MIN_WMATIC_BALANCE", 50.0)
MAIN_STRATEGY_RESERVE_SELL_FRACTION = env_float("MAIN_STRATEGY_RESERVE_SELL_FRACTION", 0.45)
MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION = env_float("MAIN_STRATEGY_CUT_LOSS_SELL_FRACTION", 0.28)
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
