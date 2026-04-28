from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from nanoclaw.utils.gas_protector import GasProtector


@dataclass(frozen=True)
class FollowedEquity:
    symbol: str
    token_address: str
    decimals: int = 18
    signal_strength: float = 0.0
    earnings_days: Optional[float] = None
    current_price_usd: Optional[float] = None


@dataclass(frozen=True)
class SignalEquityTraderConfig:
    enabled: bool = False
    followed_equities_path: str = "followed_equities.json"
    strong_signal_threshold: float = 0.85
    max_earnings_days: float = 5.0
    trade_pct_of_usdc: float = 0.18
    min_trade_usdc: float = 8.0
    max_trade_usdc: float = 28.0
    per_asset_cooldown_seconds: int = 6 * 60 * 60
    min_pol_for_gas: float = 0.05
    strong_take_profit_pct: float = 15.0


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
AssetCooldownMarkFn = Callable[[str, Optional[float], int], None]


class SignalEquityTraderBuilder:
    def __init__(self) -> None:
        self._enabled = os.getenv("ENABLE_X_SIGNAL_EQUITY", "false").lower() == "true"
        self._followed_equities_path = os.getenv("FOLLOWED_EQUITIES_PATH", "followed_equities.json")
        self._strong_signal_threshold = float(os.getenv("X_SIGNAL_STRONG_THRESHOLD", "0.85"))
        self._max_earnings_days = float(os.getenv("X_SIGNAL_MAX_EARNINGS_DAYS", "5.0"))
        self._trade_pct_of_usdc = float(os.getenv("X_SIGNAL_EQUITY_TRADE_PCT", "0.18"))
        self._min_trade_usdc = float(os.getenv("X_SIGNAL_EQUITY_MIN_TRADE", "8.0"))
        self._max_trade_usdc = float(os.getenv("X_SIGNAL_EQUITY_MAX_TRADE", "28.0"))
        self._per_asset_cooldown_seconds = int(os.getenv("X_SIGNAL_EQUITY_COOLDOWN_SECONDS", str(6 * 60 * 60)))
        self._min_pol_for_gas = float(os.getenv("MIN_POL_FOR_GAS", "0.05"))
        self._strong_take_profit_pct = float(os.getenv("X_SIGNAL_EQUITY_STRONG_TP_PCT", "15.0"))
        self._gas_protector: Optional[GasProtector] = None
        self._usdc_address: Optional[str] = os.getenv("USDC")

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
                min_trade_usdc=self._min_trade_usdc,
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
            env_token_address = str(item.get("env_token_address", symbol)).strip() or symbol
            token_address = str(os.getenv(env_token_address, "")).strip()
            if not symbol or not token_address:
                continue
            decimals = int(item.get("decimals", 18) or 18)
            signal_strength = float(item.get("signal_strength", 0.0) or 0.0)
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
        mark_asset_traded: AssetCooldownMarkFn,
        now: Optional[float] = None,
        urgent_gas: bool = False,
    ) -> Optional[EquityTradePlan]:
        if not self.config.enabled:
            return None

        sym = str(symbol).strip()
        if not sym or not token_address:
            return None

        if not self._in_earnings_window(earnings_proximity_days):
            return None

        gas_status = self.gas_protector.get_safe_status(
            address=wallet_address_for_gas,
            urgent=urgent_gas,
            min_pol=self.config.min_pol_for_gas,
        )
        if not gas_status.get("ok", False):
            return None

        if not self._cooldown_ok(sym, can_trade_asset=can_trade_asset, now=now):
            return None

        strength = float(signal_strength)
        strong = abs(strength) >= float(self.config.strong_signal_threshold)
        if not strong:
            return None

        current_time = time.time() if now is None else now

        if strength > 0:
            if usdc_balance <= 0:
                return None
            trade_size = self._compute_trade_size(usdc_balance)
            if trade_size <= 0 or trade_size > usdc_balance:
                return None
            mark_asset_traded(sym, current_time, self.config.per_asset_cooldown_seconds)
            tp = float(self.config.strong_take_profit_pct)
            price_note = f" @ ${current_price_usd:.2f}" if isinstance(current_price_usd, (int, float)) else ""
            earn_note = (
                f" | Earnings in ~{earnings_proximity_days:.1f}d"
                if isinstance(earnings_proximity_days, (int, float))
                else ""
            )
            return EquityTradePlan(
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

        if equity_balance <= 0:
            return None

        sell_fraction = float(os.getenv("X_SIGNAL_EQUITY_SELL_FRACTION", "0.55"))
        sell_fraction = min(1.0, max(0.05, sell_fraction))
        amount_in_units = int(equity_balance * sell_fraction * (10**int(token_decimals)))
        if amount_in_units <= 0:
            return None

        mark_asset_traded(sym, current_time, self.config.per_asset_cooldown_seconds)
        price_note = f" @ ${current_price_usd:.2f}" if isinstance(current_price_usd, (int, float)) else ""
        earn_note = (
            f" | Earnings in ~{earnings_proximity_days:.1f}d"
            if isinstance(earnings_proximity_days, (int, float))
            else ""
        )
        return EquityTradePlan(
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

