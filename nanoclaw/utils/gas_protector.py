"""Safe gas and POL balance checks with RPC fallback support."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Tuple, cast

from nanoclaw.config import default_json_rpc_url

try:
    from web3 import Web3 as _Web3
    Web3 = _Web3
except ImportError:  # pragma: no cover - exercised in lightweight test environments
    class Web3:  # type: ignore[no-redef]
        class _MissingEth:  # type: ignore[override]
            @property
            def gas_price(self) -> int:
                raise RuntimeError("web3 is not installed")

            def get_balance(self, _address: str) -> int:
                raise RuntimeError("web3 is not installed")

        class HTTPProvider:  # type: ignore[override]
            def __init__(self, endpoint_uri: str, request_kwargs: Optional[dict] = None) -> None:
                self.endpoint_uri = endpoint_uri
                self.request_kwargs = request_kwargs or {}

        def __init__(self, provider: Any) -> None:
            self.provider = provider
            self.eth = self._MissingEth()

        @staticmethod
        def from_wei(value: int, unit: str) -> float:
            if unit == "gwei":
                return value / 10**9
            if unit == "ether":
                return value / 10**18
            raise ValueError(f"Unsupported unit: {unit}")


SafeQuery = Callable[[Web3], float]


@dataclass(frozen=True)
class GasProtectorConfig:
    max_gwei: float = 80.0
    urgent_gwei: float = 120.0
    min_pol_balance: float = 0.05
    primary_rpc: Optional[str] = None
    fallback_rpcs: Tuple[str, ...] = ()
    retry_attempts: int = 2
    timeout_seconds: int = 10


class GasProtectorBuilder:
    def __init__(self) -> None:
        fallback_env = os.getenv("RPC_FALLBACKS", "")
        self._max_gwei = 80.0
        self._urgent_gwei = 120.0
        self._min_pol_balance = 0.05
        self._primary_rpc = default_json_rpc_url()
        self._fallback_rpcs = self._split_rpcs(fallback_env)
        self._retry_attempts = 2
        self._timeout_seconds = 10

    @staticmethod
    def _split_rpcs(raw_value: str) -> List[str]:
        return [rpc.strip() for rpc in raw_value.split(",") if rpc.strip()]

    def with_max_gwei(self, max_gwei: float) -> "GasProtectorBuilder":
        self._max_gwei = float(max_gwei)
        return self

    def with_urgent_gwei(self, urgent_gwei: float) -> "GasProtectorBuilder":
        self._urgent_gwei = float(urgent_gwei)
        return self

    def with_min_pol_balance(self, min_pol_balance: float) -> "GasProtectorBuilder":
        self._min_pol_balance = float(min_pol_balance)
        return self

    def with_primary_rpc(self, rpc_url: Optional[str]) -> "GasProtectorBuilder":
        self._primary_rpc = rpc_url.strip() if isinstance(rpc_url, str) and rpc_url.strip() else None
        return self

    def with_fallback_rpcs(self, rpc_urls: Iterable[str]) -> "GasProtectorBuilder":
        self._fallback_rpcs = [rpc.strip() for rpc in rpc_urls if isinstance(rpc, str) and rpc.strip()]
        return self

    def with_retry_attempts(self, retry_attempts: int) -> "GasProtectorBuilder":
        self._retry_attempts = max(1, int(retry_attempts))
        return self

    def with_timeout_seconds(self, timeout_seconds: int) -> "GasProtectorBuilder":
        self._timeout_seconds = max(1, int(timeout_seconds))
        return self

    def build(self) -> "GasProtector":
        config = GasProtectorConfig(
            max_gwei=self._max_gwei,
            urgent_gwei=self._urgent_gwei,
            min_pol_balance=self._min_pol_balance,
            primary_rpc=self._primary_rpc,
            fallback_rpcs=tuple(self._fallback_rpcs),
            retry_attempts=self._retry_attempts,
            timeout_seconds=self._timeout_seconds,
        )
        return GasProtector(config=config)


class GasProtector:
    def __init__(self, config: GasProtectorConfig) -> None:
        self.config = config

    @classmethod
    def builder(cls) -> GasProtectorBuilder:
        return GasProtectorBuilder()

    def _safe_high_gas_gwei(self, urgent: bool = False) -> float:
        ceiling = self.config.urgent_gwei if urgent else self.config.max_gwei
        return float(ceiling) + 1.0

    def _safe_low_pol_balance(self) -> float:
        return 0.0

    def _rpc_urls(self) -> List[str]:
        urls: List[str] = []
        for rpc_url in (self.config.primary_rpc, *self.config.fallback_rpcs):
            if rpc_url and rpc_url not in urls:
                urls.append(rpc_url)
        return urls

    def _build_web3(self, rpc_url: str) -> Web3:
        provider = Web3.HTTPProvider(
            rpc_url,
            request_kwargs={"timeout": self.config.timeout_seconds},
        )
        return Web3(provider)

    def _checksum_or_raw(self, address: str) -> str:
        converter = getattr(Web3, "to_checksum_address", None)
        if not callable(converter):
            return address
        try:
            return cast(str, converter(address))
        except Exception:
            return address

    def _query_with_fallback(self, query_fn: SafeQuery) -> Tuple[Optional[float], Optional[str]]:
        for _ in range(self.config.retry_attempts):
            for rpc_url in self._rpc_urls():
                try:
                    web3_client = self._build_web3(rpc_url)
                    return float(query_fn(web3_client)), rpc_url
                except Exception:
                    continue
        return None, None

    def get_gas_price_gwei(self) -> float:
        gas_price_gwei, _ = self._query_with_fallback(
            lambda web3_client: float(web3_client.from_wei(web3_client.eth.gas_price, "gwei"))
        )
        if gas_price_gwei is None:
            return self._safe_high_gas_gwei()
        return gas_price_gwei

    def is_gas_acceptable(self, urgent: bool = False) -> bool:
        threshold = self.config.urgent_gwei if urgent else self.config.max_gwei
        try:
            return self.get_gas_price_gwei() <= threshold
        except Exception:
            return False

    def get_pol_balance(self, address: str) -> float:
        addr = self._checksum_or_raw(address)
        pol_balance, _ = self._query_with_fallback(
            lambda web3_client: float(
                web3_client.from_wei(web3_client.eth.get_balance(cast(Any, addr)), "ether")
            )
        )
        if pol_balance is None:
            return self._safe_low_pol_balance()
        return pol_balance

    def has_enough_pol(self, address: str, min_pol: Optional[float] = None) -> bool:
        threshold = self.config.min_pol_balance if min_pol is None else float(min_pol)
        try:
            return self.get_pol_balance(address) >= threshold
        except Exception:
            return False

    def get_safe_status(self, address: str, urgent: bool = False, min_pol: Optional[float] = None) -> dict:
        threshold = self.config.urgent_gwei if urgent else self.config.max_gwei
        required_pol = self.config.min_pol_balance if min_pol is None else float(min_pol)
        addr = self._checksum_or_raw(address)
        gas_gwei, gas_rpc = self._query_with_fallback(
            lambda web3_client: float(web3_client.from_wei(web3_client.eth.gas_price, "gwei"))
        )
        pol_balance, pol_rpc = self._query_with_fallback(
            lambda web3_client: float(
                web3_client.from_wei(web3_client.eth.get_balance(cast(Any, addr)), "ether")
            )
        )

        safe_gas_gwei = self._safe_high_gas_gwei(urgent=urgent) if gas_gwei is None else gas_gwei
        safe_pol_balance = self._safe_low_pol_balance() if pol_balance is None else pol_balance

        return {
            "ok": safe_gas_gwei <= threshold and safe_pol_balance >= required_pol,
            "gas_ok": safe_gas_gwei <= threshold,
            "pol_ok": safe_pol_balance >= required_pol,
            "gas_gwei": safe_gas_gwei,
            "max_gwei": threshold,
            "pol_balance": safe_pol_balance,
            "min_pol_balance": required_pol,
            "gas_rpc": gas_rpc,
            "pol_rpc": pol_rpc,
        }
