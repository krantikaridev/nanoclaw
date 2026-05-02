from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from nanoclaw.utils.gas_protector import GasProtector


@dataclass(frozen=True)
class FollowedEquity:
    symbol: str
    token_address: str
    decimals: int = 18
    signal_strength: float = 0.0
    min_signal_strength: Optional[float] = None
    earnings_days: Optional[float] = None
    current_price_usd: Optional[float] = None


@dataclass
class SignalEquityTraderConfig:
    """Configuration for X-Signal Equity Trading (MUTABLE - use builder pattern to override)."""
    enabled: bool = False
    followed_equities_path: str = "followed_equities.json"
    strong_signal_threshold: float = 0.80
    max_earnings_days: float = 5.0
    min_signal_strength: float = 0.60
    force_high_conviction: bool = True  # If True + signal >= 0.80, bypasses most eligibility filters
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


class SignalEquityTraderBuilder:
    def __init__(self) -> None:
        self._enabled = os.getenv("ENABLE_X_SIGNAL_EQUITY", "false").lower() == "true"
        self._followed_equities_path = os.getenv("FOLLOWED_EQUITIES_PATH", "followed_equities.json")
        self._strong_signal_threshold = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.80"))
        self._max_earnings_days = float(os.getenv("X_SIGNAL_MAX_EARNINGS_DAYS", "5.0"))
        self._min_signal_strength = float(os.getenv("X_SIGNAL_EQUITY_MIN_STRENGTH", "0.60"))
        self._force_high_conviction = os.getenv("X_SIGNAL_FORCE_HIGH_CONVICTION", "true").lower() == "true"
        self._trade_pct_of_usdc = float(os.getenv("X_SIGNAL_EQUITY_TRADE_PCT", "0.18"))
        self._min_trade_usdc: Optional[float] = None
        self._max_trade_usdc = float(os.getenv("X_SIGNAL_EQUITY_MAX_TRADE", "28.0"))
        self._per_asset_cooldown_seconds = int(
            os.getenv(
                "X_SIGNAL_EQUITY_COOLDOWN_SECONDS",
                str(int(os.getenv("PER_ASSET_COOLDOWN_MINUTES", "30")) * 60),
            )
        )
        self._min_pol_for_gas = float(os.getenv("MIN_POL_FOR_GAS", "0.005"))
        self._strong_take_profit_pct = float(os.getenv("X_SIGNAL_EQUITY_STRONG_TP_PCT", "12.0"))
        self._gas_protector: Optional[GasProtector] = None
        self._usdc_address: Optional[str] = os.getenv("USDC")

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
                    else float(
                        os.getenv(
                            "X_SIGNAL_EQUITY_MIN_TRADE",
                            os.getenv("X_SIGNAL_USDC_MIN", os.getenv("AUTO_USDC_FOR_X_SIGNAL_MIN_USDC", "5.0")),
                        )
                    )
                ),
                max_trade_usdc=self._max_trade_usdc,
                per_asset_cooldown_seconds=self._per_asset_cooldown_seconds,
                min_pol_for_gas=self._min_pol_for_gas,
                strong_take_profit_pct=self._strong_take_profit_pct,
            ),
            gas_protector=self._gas_protector,
            usdc_address=self._usdc_address,
        )


class SignalEquityTrader:
    def __init__(self, config: SignalEquityTraderConfig, gas_protector: GasProtector, usdc_address: str) -> None:
        self.config = config
        self.gas_protector = gas_protector
        self.usdc_address = usdc_address

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
            token_address = explicit or str(os.getenv(env_key, "")).strip()
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
            out.append(
                FollowedEquity(
                    symbol=symbol,
                    token_address=token_address,
                    decimals=decimals,
                    signal_strength=signal_strength,
                    min_signal_strength=min_signal_strength,
                    earnings_days=earnings_days_f,
                    current_price_usd=current_price_f,
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

    def _compute_trade_size(self, usdc_balance: float) -> float:
        sized = usdc_balance * float(self.config.trade_pct_of_usdc)
        sized = max(float(self.config.min_trade_usdc), sized)
        sized = min(float(self.config.max_trade_usdc), sized)
        return max(0.0, float(sized))

    @staticmethod
    def _addrs_equal_case_insensitive(a: str, b: str) -> bool:
        return str(a).strip().lower() == str(b).strip().lower()

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
        wallet_address_for_gas: str,
        can_trade_asset: AssetCooldownGetFn,
        now: Optional[float] = None,
        urgent_gas: bool = False,
        allow_high_gas_override: bool = False,
    ) -> Tuple[Optional[EquityTradePlan], Optional[str]]:
        """Build a trade plan with detailed block reasons for DEBUG."""
        if not self.config.enabled:
            return None, "strategy_disabled"

        sym = str(symbol).strip()
        if not sym or not token_address:
            return None, "invalid_symbol_or_token"

        strength = float(signal_strength)
        is_high_conviction = (
            bool(self.config.force_high_conviction) and strength >= 0.80
        )
        
        # === ELIGIBILITY DEBUG LOG ===
        print(
            f"[nanoclaw] BUILD_PLAN_ENTRY | {sym} | signal={strength:.3f} | "
            f"force_high_conviction={self.config.force_high_conviction} | "
            f"is_high_conviction={is_high_conviction} | "
            f"strong_threshold={self.config.strong_signal_threshold:.3f}"
        )

        # === Earnings window check (applies to all) ===
        if not self._in_earnings_window(earnings_proximity_days):
            print(f"[nanoclaw] BLOCK: {sym} | outside_earnings_window (earnings_days={earnings_proximity_days})")
            return None, "outside_earnings_window"

        # === Gas check (bypassed if high_conviction + allow_override) ===
        gas_status = self.gas_protector.get_safe_status(
            address=wallet_address_for_gas,
            urgent=urgent_gas,
            min_pol=self.config.min_pol_for_gas,
        )
        gas_ok = bool(gas_status.get("gas_ok", False))
        gas_gwei = float(gas_status.get("gas_gwei", 0))
        max_gwei = float(gas_status.get("max_gwei", 0))
        
        if not gas_ok and not bool(allow_high_gas_override):
            print(f"[nanoclaw] BLOCK: {sym} | gas_above_limit ({gas_gwei:.1f} gwei > {max_gwei:.1f} gwei, no override)")
            return None, "gas_above_limit"
        
        if not gas_ok and is_high_conviction and bool(allow_high_gas_override):
            print(f"[nanoclaw] GAS OVERRIDE | {sym} | high_conviction bypass (gas {gas_gwei:.1f} > {max_gwei:.1f}, but allow_override=True)")

        # === POL check (critical safety) ===
        effective_pol = float(gas_status.get("pol_balance", 0.0) or 0.0)
        if effective_pol < float(self.config.min_pol_for_gas):
            print(f"[nanoclaw] BLOCK: {sym} | pol_below_min ({effective_pol:.4f} < {self.config.min_pol_for_gas:.4f})")
            return None, "pol_below_min"

        # === Per-asset cooldown check ===
        if not self._cooldown_ok(sym, can_trade_asset=can_trade_asset, now=now):
            print(f"[nanoclaw] BLOCK: {sym} | per_asset_cooldown ({self.config.per_asset_cooldown_seconds}s)")
            return None, "per_asset_cooldown"

        # === STRENGTH FILTER (bypassed if high_conviction) ===
        # KEY: If force_high_conviction=True AND signal >= 0.80, skip this filter entirely.
        if not is_high_conviction:
            if abs(strength) < float(self.config.strong_signal_threshold):
                print(
                    f"[nanoclaw] BLOCK: {sym} | below_strong_threshold "
                    f"({strength:.3f} < {self.config.strong_signal_threshold:.3f}; "
                    f"force_high_conviction={self.config.force_high_conviction})"
                )
                return (
                    None,
                    f"below_strong_threshold (need >={float(self.config.strong_signal_threshold):.3f})",
                )
        else:
            print(
                f"[nanoclaw] STRENGTH FILTER BYPASSED | {sym} | "
                f"force_high_conviction=True + signal={strength:.3f} >= 0.80"
            )

        # === BUY PATH ===
        if strength > 0:
            if self._addrs_equal_case_insensitive(token_address, self.usdc_address):
                print(f"[nanoclaw] BLOCK: {sym} | usdc_identity_noop")
                return None, "usdc_identity_noop"
            if usdc_balance <= 0:
                print(f"[nanoclaw] BLOCK: {sym} | zero_usdc (balance=${usdc_balance:.2f})")
                return None, "zero_usdc"
            trade_size = self._compute_trade_size(usdc_balance)
            if trade_size <= 0 or trade_size > usdc_balance:
                print(f"[nanoclaw] BLOCK: {sym} | invalid_trade_size (computed=${trade_size:.2f}, available=${usdc_balance:.2f})")
                return None, "invalid_trade_size"
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
            return plan, None

        # === SELL PATH ===
        if equity_balance <= 0:
            print(f"[nanoclaw] BLOCK: {sym} | zero_equity_balance (balance={equity_balance:.2f})")
            return None, "zero_equity_balance"

        sell_fraction = float(os.getenv("X_SIGNAL_EQUITY_SELL_FRACTION", "0.55"))
        sell_fraction = min(1.0, max(0.05, sell_fraction))
        amount_in_units = int(equity_balance * sell_fraction * (10**int(token_decimals)))
        if amount_in_units <= 0:
            print(f"[nanoclaw] BLOCK: {sym} | sell_amount_below_min_units (fraction={sell_fraction:.2f}, equity={equity_balance:.2f})")
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
        now: Optional[float] = None,
        urgent_gas: bool = False,
        allow_high_gas_override: bool = False,
    ) -> Optional[EquityTradePlan]:
        plan, _reason = self.build_plan_with_block_reason(
            symbol=symbol,
            token_address=token_address,
            token_decimals=token_decimals,
            signal_strength=signal_strength,
            earnings_proximity_days=earnings_proximity_days,
            current_price_usd=current_price_usd,
            usdc_balance=usdc_balance,
            equity_balance=equity_balance,
            wallet_address_for_gas=wallet_address_for_gas,
            can_trade_asset=can_trade_asset,
            now=now,
            urgent_gas=urgent_gas,
            allow_high_gas_override=allow_high_gas_override,
        )
        return plan

