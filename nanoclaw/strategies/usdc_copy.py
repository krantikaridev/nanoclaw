from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

from nanoclaw.utils.gas_protector import GasProtector


WalletCooldownFn = Callable[[str, Optional[float], int], bool]


@dataclass(frozen=True)
class USDCopyConfig:
    enabled: bool = False
    copy_trade_pct: float = 0.12
    min_trade_usdc: float = 5.0
    max_trade_usdc: float = 15.0
    per_wallet_cooldown_seconds: int = 300
    min_pol_for_gas: float = 0.025


@dataclass(frozen=True)
class USDCopyPlan:
    amount_in: int
    trade_size: float
    message: str
    wallet: Optional[str] = None


class USDCopyStrategyBuilder:
    def __init__(self) -> None:
        self._enabled = os.getenv("ENABLE_USDC_COPY", "false").lower() == "true"
        self._copy_trade_pct = float(os.getenv("COPY_TRADE_PCT", "0.25"))
        self._min_trade_usdc = float(os.getenv("USDC_COPY_MIN_TRADE", "5.0"))
        self._max_trade_usdc = float(os.getenv("USDC_COPY_MAX_TRADE", "15.0"))
        self._per_wallet_cooldown_seconds = int(os.getenv("PER_WALLET_COOLDOWN", "180"))
        self._min_pol_for_gas = float(os.getenv("MIN_POL_FOR_GAS", "0.025"))
        self._gas_protector: Optional[GasProtector] = None

    def with_enabled(self, enabled: bool) -> "USDCopyStrategyBuilder":
        self._enabled = bool(enabled)
        return self

    def with_copy_trade_pct(self, copy_trade_pct: float) -> "USDCopyStrategyBuilder":
        self._copy_trade_pct = float(copy_trade_pct)
        return self

    def with_min_trade_usdc(self, min_trade_usdc: float) -> "USDCopyStrategyBuilder":
        self._min_trade_usdc = float(min_trade_usdc)
        return self

    def with_max_trade_usdc(self, max_trade_usdc: float) -> "USDCopyStrategyBuilder":
        self._max_trade_usdc = float(max_trade_usdc)
        return self

    def with_per_wallet_cooldown_seconds(self, per_wallet_cooldown_seconds: int) -> "USDCopyStrategyBuilder":
        self._per_wallet_cooldown_seconds = int(per_wallet_cooldown_seconds)
        return self

    def with_min_pol_for_gas(self, min_pol_for_gas: float) -> "USDCopyStrategyBuilder":
        self._min_pol_for_gas = float(min_pol_for_gas)
        return self

    def with_gas_protector(self, gas_protector: GasProtector) -> "USDCopyStrategyBuilder":
        self._gas_protector = gas_protector
        return self

    def build(self) -> "USDCopyStrategy":
        if self._gas_protector is None:
            raise ValueError("USDCopyStrategy requires GasProtector (call with_gas_protector)")
        return USDCopyStrategy(
            config=USDCopyConfig(
                enabled=self._enabled,
                copy_trade_pct=self._copy_trade_pct,
                min_trade_usdc=self._min_trade_usdc,
                max_trade_usdc=self._max_trade_usdc,
                per_wallet_cooldown_seconds=self._per_wallet_cooldown_seconds,
                min_pol_for_gas=self._min_pol_for_gas,
            ),
            gas_protector=self._gas_protector,
        )


class USDCopyStrategy:
    def __init__(self, config: USDCopyConfig, gas_protector: GasProtector) -> None:
        self.config = config
        self.gas_protector = gas_protector

    @classmethod
    def builder(cls) -> USDCopyStrategyBuilder:
        return USDCopyStrategyBuilder()

    def _pick_wallet(
        self,
        wallets: Sequence[str],
        *,
        can_trade_wallet: WalletCooldownFn,
        now: Optional[float],
    ) -> Optional[str]:
        for wallet in wallets:
            if can_trade_wallet(wallet, now, self.config.per_wallet_cooldown_seconds):
                return wallet
        return None

    def _compute_trade_size(self, usdc_balance: float) -> float:
        sized = usdc_balance * float(self.config.copy_trade_pct)
        sized = max(float(self.config.min_trade_usdc), sized)
        sized = min(float(self.config.max_trade_usdc), sized)
        return max(0.0, float(sized))

    def build_plan(
        self,
        *,
        usdc_balance: float,
        wallets: Iterable[str],
        wallet_address_for_gas: str,
        can_trade_wallet: WalletCooldownFn,
        now: Optional[float] = None,
        urgent_gas: bool = False,
    ) -> Optional[USDCopyPlan]:
        if not self.config.enabled:
            return None

        wallet_list = [w for w in wallets if isinstance(w, str) and w.strip()]
        if not wallet_list:
            return None

        if usdc_balance <= 0:
            return None

        gas_status = self.gas_protector.get_safe_status(
            address=wallet_address_for_gas,
            urgent=urgent_gas,
            min_pol=self.config.min_pol_for_gas,
        )
        if not gas_status.get("ok", False):
            return None

        current_time = time.time() if now is None else now
        chosen_wallet = self._pick_wallet(wallet_list, can_trade_wallet=can_trade_wallet, now=current_time)
        if not chosen_wallet:
            return None

        trade_size = self._compute_trade_size(usdc_balance)
        if trade_size <= 0 or trade_size > usdc_balance:
            return None

        return USDCopyPlan(
            amount_in=int(trade_size * 1_000_000),
            trade_size=trade_size,
            wallet=chosen_wallet,
            message=f"🟦 USDC COPY: mirroring wallet {chosen_wallet[:8]}... | Size: ${trade_size:.2f} (USDC→WMATIC)",
        )

