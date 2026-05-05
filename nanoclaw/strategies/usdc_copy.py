from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

import config as cfg
from config import (
    COPY_TRADE_PCT,
    ENABLE_USDC_COPY,
    MIN_POL_FOR_GAS,
    PER_WALLET_COOLDOWN,
    USDC_COPY_MAX_TRADE,
    USDC_COPY_MIN_TRADE,
)
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
        self._enabled = ENABLE_USDC_COPY
        self._copy_trade_pct = COPY_TRADE_PCT
        self._min_trade_usdc = USDC_COPY_MIN_TRADE
        self._max_trade_usdc = USDC_COPY_MAX_TRADE
        self._per_wallet_cooldown_seconds = PER_WALLET_COOLDOWN
        self._min_pol_for_gas = MIN_POL_FOR_GAS
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
    ) -> tuple[Optional[str], float]:
        from modules import wallet_performance as wp

        ranked: list[tuple[float, str, float, dict]] = []
        for wallet in wallets:
            if not can_trade_wallet(wallet, now, self.config.per_wallet_cooldown_seconds):
                continue
            health = wp.wallet_health(wallet)
            mult = float(health.get("allocation_multiplier", 1.0))
            ranked.append((mult, wallet, mult, health))
        if not ranked:
            return None, 1.0
        ranked.sort(key=lambda row: row[0], reverse=True)
        _score, chosen, mult, health = ranked[0]
        if bool(health.get("deprioritize", False)):
            print(
                "[nanoclaw] COPY WALLET DEPRIORITIZED | "
                f"{chosen[:10]}... | trades={int(health.get('trades', 0))} "
                f"win_rate={float(health.get('win_rate', 0.0)):.2f} "
                f"avg_pnl=${float(health.get('avg_pnl_usd', 0.0)):.2f} "
                f"alloc_mult={mult:.2f}"
            )
        return chosen, mult

    def _compute_trade_size(self, usdc_balance: float, usdt_balance: float = 0.0) -> float:
        from modules import runtime

        # FIXED SIZING: $12–$20 per signal (bug fix 2026-05-03); same band as X-signal / copy paths
        cap = runtime.fixed_copy_trade_usd(
            usdc_balance, usdt_balance, float(self.config.copy_trade_pct)
        )
        hard_floor = max(0.0, float(getattr(cfg, "MIN_TRADE_USD", 15.0)))
        min_viable = max(float(self.config.min_trade_usdc), 10.0, min(hard_floor, float(self.config.max_trade_usdc)))
        sized = min(float(cap), float(usdc_balance), float(self.config.max_trade_usdc))
        if sized < min_viable and float(usdc_balance) >= min_viable:
            sized = min_viable
        return max(0.0, float(sized))

    @staticmethod
    def _estimate_gas_cost_usd(gas_gwei: float) -> float:
        est_swap_gas_units = 180000.0
        pol_price_usd = max(0.0, float(getattr(cfg, "POL_USD_PRICE", 0.0)))
        return max(0.0, (float(gas_gwei) * est_swap_gas_units / 1_000_000_000.0) * pol_price_usd)

    def build_plan(
        self,
        *,
        usdc_balance: float,
        wallets: Iterable[str],
        wallet_address_for_gas: str,
        can_trade_wallet: WalletCooldownFn,
        usdt_balance: float = 0.0,
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
        chosen_wallet, wallet_alloc_mult = self._pick_wallet(
            wallet_list, can_trade_wallet=can_trade_wallet, now=current_time
        )
        if not chosen_wallet:
            return None

        trade_size = self._compute_trade_size(usdc_balance, usdt_balance) * float(wallet_alloc_mult)
        if trade_size <= 0 or trade_size > usdc_balance:
            return None
        if wallet_alloc_mult < 1.0 and trade_size < float(cfg.COPY_MIN_MARGINAL_TRADE_USD):
            print(
                "[nanoclaw] COPY TRADE SKIPPED | marginal signal after wallet penalty "
                f"(wallet={chosen_wallet[:10]}..., size=${trade_size:.2f}, floor=${float(cfg.COPY_MIN_MARGINAL_TRADE_USD):.2f})"
            )
            return None

        gas_gwei = float(gas_status.get("gas_gwei", 0.0) or 0.0)
        gas_cost_usd = self._estimate_gas_cost_usd(gas_gwei)
        expected_edge_pct = max(0.5, float(cfg.COPY_BASE_EXPECTED_EDGE_PCT) * float(wallet_alloc_mult))
        expected_profit_usd = max(0.0, float(trade_size) * (expected_edge_pct / 100.0))
        min_expected_profit_usd = float(cfg.COPY_GAS_EDGE_MULTIPLIER) * gas_cost_usd
        effective_after_gas = float(trade_size) - gas_cost_usd
        min_effective_after_gas = float(cfg.COPY_MIN_EFFECTIVE_TRADE_AFTER_GAS_USD)
        if expected_profit_usd <= min_expected_profit_usd:
            print(
                "[nanoclaw] COPY TRADE SKIPPED | expected edge below gas threshold "
                f"(wallet={chosen_wallet[:10]}..., expected=${expected_profit_usd:.2f}, "
                f"required>${min_expected_profit_usd:.2f}, gas=${gas_cost_usd:.2f})"
            )
            return None
        if effective_after_gas < min_effective_after_gas:
            print(
                "[nanoclaw] COPY TRADE SKIPPED | effective size below gas-adjusted minimum "
                f"(wallet={chosen_wallet[:10]}..., effective=${effective_after_gas:.2f}, "
                f"required>=${min_effective_after_gas:.2f}, gas=${gas_cost_usd:.2f})"
            )
            return None

        return USDCopyPlan(
            amount_in=int(trade_size * 1_000_000),
            trade_size=trade_size,
            wallet=chosen_wallet,
            message=f"🟦 USDC COPY: mirroring wallet {chosen_wallet[:8]}... | Size: ${trade_size:.2f} (USDC→WMATIC)",
        )

