from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Tuple

import config as cfg
from config import (
    ENABLE_X_SIGNAL_EQUITY,
    FOLLOWED_EQUITIES_PATH,
    MIN_POL_FOR_GAS,
    PER_ASSET_COOLDOWN_MINUTES,
    X_SIGNAL_EQUITY_COOLDOWN_SECONDS,
    X_SIGNAL_EQUITY_MAX_TRADE,
    X_SIGNAL_EQUITY_MIN_STRENGTH,
    X_SIGNAL_EQUITY_SELL_FRACTION,
    X_SIGNAL_EQUITY_STRONG_TP_PCT,
    X_SIGNAL_EQUITY_TRADE_PCT,
    X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD,
    X_SIGNAL_FORCE_HIGH_CONVICTION,
    X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
    X_SIGNAL_MAX_EARNINGS_DAYS,
    X_SIGNAL_STRONG_THRESHOLD,
    X_SIGNAL_USDC_MIN,
    env_str,
)
from constants import LOG_PREFIX
from nanoclaw.utils.gas_protector import GasProtector

logger = logging.getLogger(__name__)

_HARD_BYPASS_ENABLED = cfg.env_bool("HARD_BYPASS_ENABLED", True)
# Hard execution floor for BUY notional; configured from .env (MIN_TRADE_USD).
_HARD_BYPASS_MIN_TRADE_USD = cfg.env_float("MIN_TRADE_USD", 15.0)


@dataclass(frozen=True)
class FollowedEquity:
    symbol: str
    token_address: str
    decimals: int = 18
    signal_strength: float = 0.0
    min_signal_strength: Optional[float] = None
    earnings_days: Optional[float] = None
    current_price_usd: Optional[float] = None
    upside_pct: Optional[float] = None


@dataclass
class SignalEquityTraderConfig:
    """Configuration for X-Signal Equity Trading (mutable dataclass; not frozen)."""
    enabled: bool = False
    followed_equities_path: str = "followed_equities.json"
    strong_signal_threshold: float = 0.80
    max_earnings_days: float = 5.0
    min_signal_strength: float = 0.60
    force_high_conviction: bool = True  # Legacy flag; bypass uses force_eligible_threshold.
    high_conviction_threshold: float = 0.80
    force_eligible_threshold: float = 0.80  # abs(signal) >= this bypasses earnings/cooldown/gas/strength bar
    trade_pct_of_usdc: float = 0.18
    min_trade_usdc: float = 5.0
    max_trade_usdc: float = 28.0
    per_asset_cooldown_seconds: int = 30 * 60
    min_pol_for_gas: float = 0.005
    strong_take_profit_pct: float = 12.0


@dataclass(frozen=True)
class EquityTradePlan:
    direction: str
    symbol: str
    token_in: str
    token_out: str
    amount_in: int
    trade_size: float
    message: str
    signal_strength: float


AssetCooldownGetFn = Callable[[str, Optional[float], int], bool]


@dataclass(frozen=True)
class EquityBuildPlanParams:
    """Encapsulates kwargs for ``build_plan_with_block_reason`` (reduces long call sites in signal orchestration)."""

    symbol: str
    token_address: str
    token_decimals: int
    signal_strength: float
    earnings_proximity_days: Optional[float]
    current_price_usd: Optional[float]
    usdc_balance: float
    equity_balance: float
    usdt_balance: float
    wallet_address_for_gas: str
    can_trade_asset: AssetCooldownGetFn
    now: Optional[float] = None
    urgent_gas: bool = False
    allow_high_gas_override: bool = False
    upside_pct: Optional[float] = None

    @classmethod
    def for_eligible_asset(
        cls,
        asset: FollowedEquity,
        *,
        usdc_balance: float,
        usdt_balance: float,
        equity_balance: float,
        wallet_address_for_gas: str,
        can_trade_asset: AssetCooldownGetFn,
        allow_high_gas_override: bool,
    ) -> EquityBuildPlanParams:
        return cls(
            symbol=str(asset.symbol).strip(),
            token_address=str(asset.token_address).strip(),
            token_decimals=int(asset.decimals),
            signal_strength=float(asset.signal_strength),
            earnings_proximity_days=asset.earnings_days,
            current_price_usd=asset.current_price_usd,
            usdc_balance=usdc_balance,
            equity_balance=equity_balance,
            usdt_balance=usdt_balance,
            wallet_address_for_gas=wallet_address_for_gas,
            can_trade_asset=can_trade_asset,
            allow_high_gas_override=allow_high_gas_override,
            upside_pct=asset.upside_pct,
        )


class SignalEquityTraderBuilder:
    def __init__(self) -> None:
        self._enabled = cfg.env_bool("ENABLE_X_SIGNAL_EQUITY", ENABLE_X_SIGNAL_EQUITY)
        self._followed_equities_path = cfg.env_str("FOLLOWED_EQUITIES_PATH", FOLLOWED_EQUITIES_PATH)
        self._strong_signal_threshold = cfg.env_float("X_SIGNAL_STRONG_THRESHOLD", X_SIGNAL_STRONG_THRESHOLD)
        self._max_earnings_days = cfg.env_float("X_SIGNAL_MAX_EARNINGS_DAYS", X_SIGNAL_MAX_EARNINGS_DAYS)
        self._min_signal_strength = cfg.env_float("X_SIGNAL_EQUITY_MIN_STRENGTH", X_SIGNAL_EQUITY_MIN_STRENGTH)
        self._force_high_conviction = cfg.env_bool("X_SIGNAL_FORCE_HIGH_CONVICTION", X_SIGNAL_FORCE_HIGH_CONVICTION)
        self._high_conviction_threshold = cfg.env_float(
            "X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD",
            X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
        )
        self._force_eligible_threshold = cfg.env_float(
            "X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD",
            X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD,
        )
        self._trade_pct_of_usdc = cfg.env_float("X_SIGNAL_EQUITY_TRADE_PCT", X_SIGNAL_EQUITY_TRADE_PCT)
        self._min_trade_usdc: Optional[float] = None
        self._max_trade_usdc = cfg.env_float("X_SIGNAL_EQUITY_MAX_TRADE", X_SIGNAL_EQUITY_MAX_TRADE)
        self._per_asset_cooldown_seconds = cfg.env_int(
            "X_SIGNAL_EQUITY_COOLDOWN_SECONDS",
            X_SIGNAL_EQUITY_COOLDOWN_SECONDS or (PER_ASSET_COOLDOWN_MINUTES * 60),
        )
        self._min_pol_for_gas = cfg.env_float("MIN_POL_FOR_GAS", MIN_POL_FOR_GAS)
        self._strong_take_profit_pct = cfg.env_float("X_SIGNAL_EQUITY_STRONG_TP_PCT", X_SIGNAL_EQUITY_STRONG_TP_PCT)
        self._gas_protector: Optional[GasProtector] = None
        self._usdc_address: Optional[str] = cfg.env_str("USDC", "")

    @staticmethod
    def _is_valid_polygon_address(token_address: str) -> bool:
        addr = str(token_address or "").strip()
        return addr.startswith("0x") and len(addr) == 42

    def with_enabled(self, enabled: bool) -> "SignalEquityTraderBuilder":
        self._enabled = bool(enabled)
        return self

    def with_followed_equities_path(self, path: str) -> "SignalEquityTraderBuilder":
        self._followed_equities_path = str(path)
        return self

    def with_strong_signal_threshold(self, strong_signal_threshold: float) -> "SignalEquityTraderBuilder":
        self._strong_signal_threshold = float(strong_signal_threshold)
        return self

    def with_max_earnings_days(self, max_earnings_days: float) -> "SignalEquityTraderBuilder":
        self._max_earnings_days = float(max_earnings_days)
        return self

    def with_trade_pct_of_usdc(self, trade_pct_of_usdc: float) -> "SignalEquityTraderBuilder":
        self._trade_pct_of_usdc = float(trade_pct_of_usdc)
        return self

    def with_min_trade_usdc(self, min_trade_usdc: float) -> "SignalEquityTraderBuilder":
        self._min_trade_usdc = float(min_trade_usdc)
        return self

    def with_max_trade_usdc(self, max_trade_usdc: float) -> "SignalEquityTraderBuilder":
        self._max_trade_usdc = float(max_trade_usdc)
        return self

    def with_per_asset_cooldown_seconds(self, per_asset_cooldown_seconds: int) -> "SignalEquityTraderBuilder":
        self._per_asset_cooldown_seconds = int(per_asset_cooldown_seconds)
        return self

    def with_min_signal_strength(self, min_signal_strength: float) -> "SignalEquityTraderBuilder":
        self._min_signal_strength = float(min_signal_strength)
        return self

    def with_force_high_conviction(self, force_high_conviction: bool) -> "SignalEquityTraderBuilder":
        self._force_high_conviction = bool(force_high_conviction)
        return self

    def with_high_conviction_threshold(self, high_conviction_threshold: float) -> "SignalEquityTraderBuilder":
        self._high_conviction_threshold = float(high_conviction_threshold)
        return self

    def with_force_eligible_threshold(self, force_eligible_threshold: float) -> "SignalEquityTraderBuilder":
        self._force_eligible_threshold = float(force_eligible_threshold)
        return self

    def with_min_pol_for_gas(self, min_pol_for_gas: float) -> "SignalEquityTraderBuilder":
        self._min_pol_for_gas = float(min_pol_for_gas)
        return self

    def with_strong_take_profit_pct(self, strong_take_profit_pct: float) -> "SignalEquityTraderBuilder":
        self._strong_take_profit_pct = float(strong_take_profit_pct)
        return self

    def with_usdc_address(self, usdc_address: str) -> "SignalEquityTraderBuilder":
        self._usdc_address = str(usdc_address)
        return self

    def with_gas_protector(self, gas_protector: GasProtector) -> "SignalEquityTraderBuilder":
        self._gas_protector = gas_protector
        return self

    def build(self) -> "SignalEquityTrader":
        if self._gas_protector is None:
            raise ValueError("SignalEquityTrader requires GasProtector (call with_gas_protector)")
        if not self._usdc_address:
            raise ValueError("SignalEquityTrader requires USDC address (env USDC or with_usdc_address)")
        return SignalEquityTrader(
            config=SignalEquityTraderConfig(
                enabled=self._enabled,
                followed_equities_path=self._followed_equities_path,
                strong_signal_threshold=self._strong_signal_threshold,
                max_earnings_days=self._max_earnings_days,
                trade_pct_of_usdc=self._trade_pct_of_usdc,
                min_signal_strength=self._min_signal_strength,
                force_high_conviction=self._force_high_conviction,
                min_trade_usdc=(
                    self._min_trade_usdc
                    if self._min_trade_usdc is not None
                    else float(cfg.env_float("X_SIGNAL_EQUITY_MIN_TRADE", X_SIGNAL_USDC_MIN))
                ),
                max_trade_usdc=self._max_trade_usdc,
                per_asset_cooldown_seconds=self._per_asset_cooldown_seconds,
                min_pol_for_gas=self._min_pol_for_gas,
                strong_take_profit_pct=self._strong_take_profit_pct,
                high_conviction_threshold=self._high_conviction_threshold,
                force_eligible_threshold=self._force_eligible_threshold,
            ),
            gas_protector=self._gas_protector,
            usdc_address=self._usdc_address,
        )


class SignalEquityTrader:
    _ERC20_BALANCE_OF_ABI = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        }
    ]
    _PROFIT_TO_GAS_MULTIPLIER = 2.5
    _MIN_EFFECTIVE_TRADE_AFTER_GAS_USD = 8.0
    _LIMITED_USDC_FORCE_ELIGIBLE_THRESHOLD = 0.85

    def __init__(self, config: SignalEquityTraderConfig, gas_protector: GasProtector, usdc_address: str) -> None:
        self.config = config
        self.gas_protector = gas_protector
        self.usdc_address = usdc_address
        self.last_usdc_balance_source = "not_queried"
        self._last_known_good_usdc_balance: Optional[float] = None

    @classmethod
    def builder(cls) -> SignalEquityTraderBuilder:
        return SignalEquityTraderBuilder()

    def load_followed_equities(self) -> Sequence[FollowedEquity]:
        path = Path(self.config.followed_equities_path)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

        assets = raw.get("assets", []) if isinstance(raw, dict) else []
        out: list[FollowedEquity] = []
        for item in assets:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).strip()
            env_key = str(item.get("env_token_address", symbol)).strip() or symbol
            explicit_address = item.get("address")
            explicit = str(explicit_address).strip() if explicit_address is not None else ""
            token_address = explicit or env_str(env_key, "")
            if not symbol or not token_address:
                if symbol:
                    print(f"[nanoclaw] TRADE SKIPPED: invalid asset config ({symbol}: missing token address)")
                continue
            if not SignalEquityTraderBuilder._is_valid_polygon_address(token_address):
                print(f"[nanoclaw] TRADE SKIPPED: invalid asset config ({symbol}: bad Polygon address '{token_address}')")
                continue
            decimals = int(item.get("decimals", 18) or 18)
            signal_strength = float(item.get("signal_strength", 0.0) or 0.0)
            min_signal_strength = item.get("min_signal_strength", None)
            if min_signal_strength is not None:
                try:
                    min_signal_strength = float(min_signal_strength)
                except Exception:
                    min_signal_strength = None
            # Tier 1 liquidity configs may define per-asset signal floor; keep only sane values.
            if isinstance(min_signal_strength, (int, float)) and not (0.0 <= float(min_signal_strength) <= 1.0):
                min_signal_strength = None
            earnings_days = item.get("earnings_days", None)
            earnings_days_f = float(earnings_days) if earnings_days is not None else None
            current_price = item.get("current_price_usd", None)
            current_price_f = float(current_price) if current_price is not None else None
            up = item.get("upside_pct", None)
            upside_f = float(up) if up is not None else None
            out.append(
                FollowedEquity(
                    symbol=symbol,
                    token_address=token_address,
                    decimals=decimals,
                    signal_strength=signal_strength,
                    min_signal_strength=min_signal_strength,
                    earnings_days=earnings_days_f,
                    current_price_usd=current_price_f,
                    upside_pct=upside_f,
                )
            )
        return out

    def _in_earnings_window(self, earnings_days: Optional[float]) -> bool:
        if earnings_days is None:
            return True
        return float(earnings_days) <= float(self.config.max_earnings_days)

    def _cooldown_ok(self, symbol: str, *, can_trade_asset: AssetCooldownGetFn, now: Optional[float]) -> bool:
        current_time = time.time() if now is None else now
        return can_trade_asset(symbol, current_time, self.config.per_asset_cooldown_seconds)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _dedupe_endpoints(endpoints: Sequence[str]) -> list[str]:
        out: list[str] = []
        for endpoint in endpoints:
            normalized = str(endpoint).strip()
            if normalized and normalized not in out:
                out.append(normalized)
        return out

    def _rpc_endpoints_for_usdc_query(self) -> list[str]:
        configured_raw = cfg.env_str("RPC_ENDPOINTS", "")
        configured = [part.strip() for part in configured_raw.split(",") if part.strip()]
        singles = [
            cfg.env_str("RPC", ""),
            cfg.env_str("RPC_URL", ""),
            cfg.env_str("WEB3_PROVIDER_URI", ""),
        ]
        static_cfg_endpoints = [str(url).strip() for url in getattr(cfg, "RPC_ENDPOINTS", [])]
        return self._dedupe_endpoints([*configured, *singles, *static_cfg_endpoints])

    def _query_onchain_usdc_balance(self, fallback_balance: float) -> float:
        """Read wallet USDC balance directly from chain with endpoint fallback and retries."""
        wallet = cfg.env_str("WALLET", "")
        token = cfg.env_str("USDC", self.usdc_address)
        per_rpc_attempts = max(2, int(cfg.env_int("X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS", 2)))
        if not wallet or not token:
            self.last_usdc_balance_source = "fallback_missing_wallet_or_token"
            logger.warning(
                "on-chain USDC balance query skipped (missing wallet/token); using fallback balance: $%.2f",
                float(fallback_balance),
            )
            return float(fallback_balance)

        rpc_endpoints = self._rpc_endpoints_for_usdc_query()
        if not rpc_endpoints:
            from nanoclaw.config import default_json_rpc_url

            rpc_endpoints = self._dedupe_endpoints(default_json_rpc_url())

        if not rpc_endpoints:
            self.last_usdc_balance_source = "fallback_missing_rpc_endpoints"
            logger.warning(
                "on-chain USDC balance query skipped (no RPC endpoints configured); using fallback balance: $%.2f",
                float(fallback_balance),
            )
            return float(fallback_balance)

        last_error: Optional[Exception] = None
        for endpoint in rpc_endpoints:
            logger.info("Trying RPC endpoint: %s", endpoint)
            for attempt in range(1, per_rpc_attempts + 1):
                try:
                    from nanoclaw.config import connect_web3
                    from web3 import Web3

                    web3_client = connect_web3(urls=[endpoint])
                    checksum_wallet = Web3.to_checksum_address(wallet)
                    checksum_token = Web3.to_checksum_address(token)
                    contract = web3_client.eth.contract(address=checksum_token, abi=self._ERC20_BALANCE_OF_ABI)
                    raw_balance = contract.functions.balanceOf(checksum_wallet).call()
                    onchain_balance = float(raw_balance) / 1_000_000.0
                    if not math.isfinite(onchain_balance) or onchain_balance < 0.0:
                        raise ValueError(f"invalid on-chain USDC balance {onchain_balance!r}")
                    self._last_known_good_usdc_balance = onchain_balance
                    self.last_usdc_balance_source = "onchain"
                    logger.info(
                        "Successfully fetched on-chain USDC balance via %s (attempt %d/%d): $%.2f",
                        endpoint,
                        attempt,
                        per_rpc_attempts,
                        onchain_balance,
                    )
                    return onchain_balance
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "RPC %s failed (attempt %d/%d): %s",
                        endpoint,
                        attempt,
                        per_rpc_attempts,
                        exc,
                    )
            logger.warning("Falling back to next RPC after failures on %s", endpoint)

        if (
            isinstance(self._last_known_good_usdc_balance, (int, float))
            and math.isfinite(float(self._last_known_good_usdc_balance))
            and float(self._last_known_good_usdc_balance) >= 0.0
        ):
            self.last_usdc_balance_source = "fallback_last_known_good"
            logger.warning(
                "All RPC endpoints failed; using last known good on-chain USDC balance: $%.2f | last_error=%s",
                float(self._last_known_good_usdc_balance),
                last_error,
            )
            return float(self._last_known_good_usdc_balance)

        self.last_usdc_balance_source = "fallback_after_all_rpcs_failed"
        logger.warning(
            "All RPC endpoints failed; using snapshot fallback balance: $%.2f | last_error=%s",
            float(fallback_balance),
            last_error,
        )
        return float(fallback_balance)

    def _estimate_gas_cost_usd(self, gas_gwei: float) -> float:
        # Approximate ERC20 swap gas on Polygon; converted with env-driven POL_USD_PRICE.
        est_swap_gas_units = 180000.0
        pol_price_usd = max(0.0, float(getattr(cfg, "POL_USD_PRICE", 0.0)))
        return max(0.0, (float(gas_gwei) * est_swap_gas_units / 1_000_000_000.0) * pol_price_usd)

    def _expected_profit_usd(self, trade_size: float, upside_pct: Optional[float]) -> float:
        if isinstance(upside_pct, (int, float)) and float(upside_pct) > 0:
            expected_edge_pct = float(upside_pct)
        else:
            expected_edge_pct = max(0.0, float(self.config.strong_take_profit_pct))
        return max(0.0, float(trade_size) * (expected_edge_pct / 100.0))

    def _effective_force_eligible_threshold(self, usdc_balance: float) -> float:
        """Raise force-eligible bar when USDC is limited to prioritize strongest signals only."""
        base_threshold = float(self.config.force_eligible_threshold)
        usdc_safe_floor = float(cfg.env_float("X_SIGNAL_USDC_SAFE_FLOOR", 20.0))
        if float(usdc_balance) < usdc_safe_floor:
            return max(base_threshold, float(self._LIMITED_USDC_FORCE_ELIGIBLE_THRESHOLD))
        return base_threshold

    def _compute_trade_size(
        self,
        usdc_balance: float,
        signal_strength: float,
        usdt_balance: float = 0.0,
        *,
        symbol: str = "",
    ) -> float:
        """USD size between FIXED_TRADE_USD_MIN/MAX (runtime), scaled by |signal| vs strong threshold; capped by USDC."""
        from modules import runtime as rt

        # Keep strategy dynamic but never in the gas-killed micro-trade band.
        lo = max(float(rt.FIXED_TRADE_USD_MIN), 8.0)
        hi = max(float(rt.FIXED_TRADE_USD_MAX), 12.0)
        if hi < lo:
            lo, hi = hi, lo
        thr = float(self.config.strong_signal_threshold)
        s_abs = abs(float(signal_strength))
        if thr >= 1.0:
            t = 1.0
        else:
            t = (s_abs - thr) / (1.0 - thr)
        t = max(0.0, min(1.0, t))
        raw = lo + (hi - lo) * t
        sized = min(float(raw), float(usdc_balance), float(self.config.max_trade_usdc))
        _lp = (LOG_PREFIX or "").strip() or "[nanoclaw]"
        print(f"{_lp} DYNAMIC SIZING | Size=${sized:.2f} | Signal={float(signal_strength):.2f}")
        return max(0.0, float(sized))

    @staticmethod
    def _addrs_equal_case_insensitive(a: str, b: str) -> bool:
        return str(a).strip().lower() == str(b).strip().lower()

    def build_plan_from_params(
        self, params: EquityBuildPlanParams
    ) -> Tuple[Optional[EquityTradePlan], Optional[str]]:
        return self.build_plan_with_block_reason(
            symbol=params.symbol,
            token_address=params.token_address,
            token_decimals=params.token_decimals,
            signal_strength=params.signal_strength,
            earnings_proximity_days=params.earnings_proximity_days,
            current_price_usd=params.current_price_usd,
            usdc_balance=params.usdc_balance,
            equity_balance=params.equity_balance,
            usdt_balance=params.usdt_balance,
            wallet_address_for_gas=params.wallet_address_for_gas,
            can_trade_asset=params.can_trade_asset,
            now=params.now,
            urgent_gas=params.urgent_gas,
            allow_high_gas_override=params.allow_high_gas_override,
            upside_pct=params.upside_pct,
        )

    def build_plan_with_block_reason(
        self,
        *,
        symbol: str,
        token_address: str,
        token_decimals: int,
        signal_strength: float,
        earnings_proximity_days: Optional[float],
        current_price_usd: Optional[float],
        usdc_balance: float,
        equity_balance: float,
        usdt_balance: float = 0.0,
        wallet_address_for_gas: str,
        can_trade_asset: AssetCooldownGetFn,
        now: Optional[float] = None,
        urgent_gas: bool = False,
        allow_high_gas_override: bool = False,
        upside_pct: Optional[float] = None,
    ) -> Tuple[Optional[EquityTradePlan], Optional[str]]:
        """Build a trade plan with detailed block reasons for DEBUG."""
        if not self.config.enabled:
            print("[nanoclaw] BLOCK: strategy_disabled")
            logger.debug("build_plan block reason=strategy_disabled")
            return None, "strategy_disabled"

        sym = str(symbol).strip()
        if not sym or not token_address:
            print(f"[nanoclaw] BLOCK: invalid_symbol_or_token (symbol={symbol!r}, token_address={token_address!r})")
            logger.debug("build_plan block reason=invalid_symbol_or_token sym=%r token=%r", symbol, token_address)
            return None, "invalid_symbol_or_token"

        strength = float(signal_strength)
        effective_usdc_balance = float(usdc_balance)
        # For BUY eligibility, use fresh on-chain USDC so force-eligible threshold reflects real liquidity.
        if strength > 0 and not self._addrs_equal_case_insensitive(token_address, self.usdc_address):
            effective_usdc_balance = self._to_float(self._query_onchain_usdc_balance(usdc_balance), usdc_balance)
        fe_thr = self._effective_force_eligible_threshold(effective_usdc_balance)
        is_force_eligible = abs(strength) >= fe_thr

        logger.debug(
            "build_plan_with_block_reason entry sym=%s signal=%s fe_thr=%s is_force_eligible=%s usdc_for_eligibility=%s",
            sym,
            strength,
            fe_thr,
            is_force_eligible,
            effective_usdc_balance,
        )

        # === Earnings window check (bypass if force-eligible) ===
        if not is_force_eligible and not self._in_earnings_window(earnings_proximity_days):
            print(f"[nanoclaw] BLOCK: {sym} | outside_earnings_window (earnings_days={earnings_proximity_days})")
            logger.debug("build_plan block sym=%s reason=outside_earnings_window", sym)
            return None, "outside_earnings_window"

        # === Gas check (bypass if force-eligible) ===
        gas_status = self.gas_protector.get_safe_status(
            address=wallet_address_for_gas,
            urgent=urgent_gas,
            min_pol=self.config.min_pol_for_gas,
        )
        gas_ok = bool(gas_status.get("gas_ok", False))
        gas_gwei = float(gas_status.get("gas_gwei", 0))
        max_gwei = float(gas_status.get("max_gwei", 0))

        if not gas_ok and not is_force_eligible and not bool(allow_high_gas_override):
            print(f"[nanoclaw] BLOCK: {sym} | gas_above_limit ({gas_gwei:.1f} gwei > {max_gwei:.1f} gwei, no override)")
            logger.debug("build_plan block sym=%s reason=gas_above_limit", sym)
            return None, "gas_above_limit"

        if not gas_ok and is_force_eligible and bool(allow_high_gas_override):
            print(f"[nanoclaw] GAS OVERRIDE | {sym} | high_conviction bypass (gas {gas_gwei:.1f} > {max_gwei:.1f}, allow_high_gas_override=True)")

        # === POL check (bypass when high-conviction X-SIGNAL: |signal| > 0.85) ===
        effective_pol = float(gas_status.get("pol_balance", 0.0) or 0.0)
        high_conviction_pol_bypass = abs(float(strength)) > 0.85
        if effective_pol < float(self.config.min_pol_for_gas) and not high_conviction_pol_bypass:
            print(f"[nanoclaw] BLOCK: {sym} | pol_below_min ({effective_pol:.4f} < {self.config.min_pol_for_gas:.4f})")
            logger.debug("build_plan block sym=%s reason=pol_below_min", sym)
            return None, "pol_below_min"

        # === Per-asset cooldown (bypass if force-eligible) ===
        if not is_force_eligible and not self._cooldown_ok(sym, can_trade_asset=can_trade_asset, now=now):
            print(f"[nanoclaw] BLOCK: {sym} | per_asset_cooldown ({self.config.per_asset_cooldown_seconds}s)")
            logger.debug("build_plan block sym=%s reason=per_asset_cooldown", sym)
            return None, "per_asset_cooldown"
        if is_force_eligible and not self._cooldown_ok(sym, can_trade_asset=can_trade_asset, now=now):
            print(f"[nanoclaw] COOLDOWN OVERRIDE | {sym} | force_eligible bypass ({self.config.per_asset_cooldown_seconds}s)")

        # === STRENGTH FILTER (bypass if force-eligible) ===
        if not is_force_eligible:
            if abs(strength) < float(self.config.strong_signal_threshold):
                print(
                    f"[nanoclaw] BLOCK: {sym} | below_strong_threshold "
                    f"({strength:.3f} < {self.config.strong_signal_threshold:.3f})"
                )
                logger.debug("build_plan block sym=%s reason=below_strong_threshold", sym)
                return (
                    None,
                    f"below_strong_threshold (need >={float(self.config.strong_signal_threshold):.3f})",
                )
        else:
            print(
                f"[nanoclaw] STRENGTH FILTER BYPASSED | {sym} | "
                f"abs(signal)>={fe_thr:.3f} (force-eligible)"
            )

        # === BUY PATH ===
        if strength > 0:
            if self._addrs_equal_case_insensitive(token_address, self.usdc_address):
                print(f"[nanoclaw] BLOCK: {sym} | usdc_identity_noop")
                logger.debug("build_plan block sym=%s reason=usdc_identity_noop", sym)
                return None, "usdc_identity_noop"
            usdc_balance = self._to_float(effective_usdc_balance, 0.0)
            if usdc_balance <= 0:
                print(
                    f"[nanoclaw] BLOCK: {sym} | zero_usdc (balance=${usdc_balance:.2f}, "
                    f"source={self.last_usdc_balance_source})"
                )
                logger.debug("build_plan block sym=%s reason=zero_usdc", sym)
                return None, "zero_usdc"
            trade_size = self._compute_trade_size(usdc_balance, strength, usdt_balance, symbol=sym)
            if trade_size <= 0 or trade_size > usdc_balance:
                print(f"[nanoclaw] BLOCK: {sym} | invalid_trade_size (computed=${trade_size:.2f}, available=${usdc_balance:.2f})")
                logger.debug("build_plan block sym=%s reason=invalid_trade_size", sym)
                return None, "invalid_trade_size"
            min_sz = float(self.config.min_trade_usdc)
            if trade_size < min_sz:
                print(
                    f"[nanoclaw] BLOCK: {sym} | below_min_trade_usdc "
                    f"(computed=${trade_size:.2f} < min=${min_sz:.2f})"
                )
                logger.debug("build_plan block sym=%s reason=below_min_trade_usdc", sym)
                return None, "below_min_trade_usdc"
            trade_amount_usd = trade_size
            if _HARD_BYPASS_ENABLED and trade_amount_usd < float(_HARD_BYPASS_MIN_TRADE_USD):
                logger.warning(
                    "[HARD BYPASS] Small trade $%.2f < $%.2f — skipped",
                    trade_amount_usd,
                    float(_HARD_BYPASS_MIN_TRADE_USD),
                )
                return None, "small_trade_bypass"
            gas_cost_usd = self._estimate_gas_cost_usd(gas_gwei)
            expected_profit_usd = self._expected_profit_usd(trade_size, upside_pct)
            min_expected_profit_usd = gas_cost_usd * float(self._PROFIT_TO_GAS_MULTIPLIER)
            effective_trade_size_after_gas = trade_size - gas_cost_usd
            print(
                f"[nanoclaw] SIZING DECISION | {sym} | signal={strength:.2f} | size=${trade_size:.2f} | "
                f"gas=${gas_cost_usd:.2f} | expected=${expected_profit_usd:.2f} | "
                f"required_expected>${min_expected_profit_usd:.2f} | effective_after_gas=${effective_trade_size_after_gas:.2f}"
            )
            if expected_profit_usd <= min_expected_profit_usd:
                print(
                    f"[nanoclaw] BLOCK: {sym} | expected_profit_below_gas "
                    f"(expected=${expected_profit_usd:.2f} <= required=${min_expected_profit_usd:.2f}, gas=${gas_cost_usd:.2f})"
                )
                logger.debug(
                    "build_plan block sym=%s reason=expected_profit_below_gas expected=%s required=%s gas=%s",
                    sym,
                    expected_profit_usd,
                    min_expected_profit_usd,
                    gas_cost_usd,
                )
                return None, "expected_profit_below_gas"
            if effective_trade_size_after_gas < float(self._MIN_EFFECTIVE_TRADE_AFTER_GAS_USD):
                print(
                    f"[nanoclaw] BLOCK: {sym} | low_effective_trade_after_gas "
                    f"(effective=${effective_trade_size_after_gas:.2f} < ${self._MIN_EFFECTIVE_TRADE_AFTER_GAS_USD:.2f})"
                )
                logger.debug(
                    "build_plan block sym=%s reason=low_effective_trade_after_gas effective=%s gas=%s",
                    sym,
                    effective_trade_size_after_gas,
                    gas_cost_usd,
                )
                return None, "low_effective_trade_after_gas"
            tp = float(self.config.strong_take_profit_pct)
            price_note = f" @ ${current_price_usd:.2f}" if isinstance(current_price_usd, (int, float)) else ""
            earn_note = (
                f" | Earnings in ~{earnings_proximity_days:.1f}d"
                if isinstance(earnings_proximity_days, (int, float))
                else ""
            )
            plan = EquityTradePlan(
                direction="USDC_TO_EQUITY",
                symbol=sym,
                token_in=self.usdc_address,
                token_out=token_address,
                amount_in=int(trade_size * 1_000_000),
                trade_size=trade_size,
                signal_strength=strength,
                message=(
                    f"🟪 X-SIGNAL EQUITY BUY: {sym}{price_note} | Strength {strength:.2f}{earn_note} | "
                    f"TP {tp:.0f}% | Size: ${trade_size:.2f} (USDC→{sym})"
                ),
            )
            print(f"[nanoclaw] PLAN_BUILD_SUCCESS | {sym} | BUY | ${trade_size:.2f}")
            exp_pnl = (
                float(trade_size) * (float(upside_pct) / 100.0)
                if isinstance(upside_pct, (int, float))
                else 0.0
            )
            print(
                f"TRADE_ATTRIBUTION | Asset={sym} | Size=${trade_size:.2f} | Signal={strength:.2f} | "
                f"Wallet=X-SIGNAL | Expected_PnL={exp_pnl:.2f}"
            )
            logger.debug("build_plan success sym=%s direction=BUY trade_size=%s", sym, trade_size)
            return plan, None

        # === SELL PATH ===
        if equity_balance <= 0:
            print(f"[nanoclaw] BLOCK: {sym} | zero_equity_balance (balance={equity_balance:.2f})")
            logger.debug("build_plan block sym=%s reason=zero_equity_balance", sym)
            return None, "zero_equity_balance"

        sell_fraction = float(X_SIGNAL_EQUITY_SELL_FRACTION)
        sell_fraction = min(1.0, max(0.05, sell_fraction))
        amount_in_units = int(equity_balance * sell_fraction * (10**int(token_decimals)))
        if amount_in_units <= 0:
            print(f"[nanoclaw] BLOCK: {sym} | sell_amount_below_min_units (fraction={sell_fraction:.2f}, equity={equity_balance:.2f})")
            logger.debug("build_plan block sym=%s reason=sell_amount_below_min_units", sym)
            return None, "sell_amount_below_min_units"

        price_note = f" @ ${current_price_usd:.2f}" if isinstance(current_price_usd, (int, float)) else ""
        earn_note = (
            f" | Earnings in ~{earnings_proximity_days:.1f}d"
            if isinstance(earnings_proximity_days, (int, float))
            else ""
        )
        plan = EquityTradePlan(
            direction="EQUITY_TO_USDC",
            symbol=sym,
            token_in=token_address,
            token_out=self.usdc_address,
            amount_in=amount_in_units,
            trade_size=0.0,
            signal_strength=strength,
            message=(
                f"🟪 X-SIGNAL EQUITY SELL: {sym}{price_note} | Strength {strength:.2f}{earn_note} | "
                f"Selling {sell_fraction * 100:.0f}% ( {sym}→USDC )"
            ),
        )
        print(f"[nanoclaw] PLAN_BUILD_SUCCESS | {sym} | SELL | {sell_fraction*100:.0f}%")
        sell_sz = (
            float(equity_balance) * float(sell_fraction) * float(current_price_usd)
            if isinstance(current_price_usd, (int, float))
            else 0.0
        )
        exp_pnl = sell_sz * (float(upside_pct) / 100.0) if isinstance(upside_pct, (int, float)) else 0.0
        print(
            f"TRADE_ATTRIBUTION | Asset={sym} | Size=${sell_sz:.2f} | Signal={strength:.2f} | "
            f"Wallet=X-SIGNAL | Expected_PnL={exp_pnl:.2f}"
        )
        logger.debug("build_plan success sym=%s direction=SELL fraction=%s", sym, sell_fraction)
        return plan, None

    def build_plan(
        self,
        *,
        symbol: str,
        token_address: str,
        token_decimals: int,
        signal_strength: float,
        earnings_proximity_days: Optional[float],
        current_price_usd: Optional[float],
        usdc_balance: float,
        equity_balance: float,
        wallet_address_for_gas: str,
        can_trade_asset: AssetCooldownGetFn,
        usdt_balance: float = 0.0,
        now: Optional[float] = None,
        urgent_gas: bool = False,
        allow_high_gas_override: bool = False,
        upside_pct: Optional[float] = None,
    ) -> Optional[EquityTradePlan]:
        logger.debug(
            "build_plan entry sym=%s signal=%s usdc=%s equity=%s",
            symbol,
            signal_strength,
            usdc_balance,
            equity_balance,
        )
        plan, reason = self.build_plan_with_block_reason(
            symbol=symbol,
            token_address=token_address,
            token_decimals=token_decimals,
            signal_strength=signal_strength,
            earnings_proximity_days=earnings_proximity_days,
            current_price_usd=current_price_usd,
            usdc_balance=usdc_balance,
            equity_balance=equity_balance,
            usdt_balance=usdt_balance,
            wallet_address_for_gas=wallet_address_for_gas,
            can_trade_asset=can_trade_asset,
            now=now,
            urgent_gas=urgent_gas,
            allow_high_gas_override=allow_high_gas_override,
            upside_pct=upside_pct,
        )
        if plan is None:
            logger.debug("build_plan exit None sym=%s reason=%s", symbol, reason)
        else:
            logger.debug("build_plan exit OK sym=%s direction=%s", symbol, plan.direction)
        return plan

