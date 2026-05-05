"""Central configuration - Single Source of Truth (SRP)"""

import logging
import time
from dataclasses import dataclass
from typing import Any, List, Sequence

from config import (
    RPC,
    RPC_ENDPOINTS,
    RPC_FALLBACKS,
    RPC_URL,
    WEB3_PROVIDER_URI,
    X_SIGNAL_DYNAMIC_TIER_HIGH_MIN,
    X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE,
    X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE,
    X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH,
)
_DEFAULT_POLYGON_PUBLIC_RPCS: tuple[str, ...] = (
    "https://rpc.ankr.com/polygon",
    "https://polygon.llamarpc.com",
    "https://polygon.drpc.org",
    "https://polygon-rpc.com",
)

# Per-endpoint: first attempt + 2 retries, 1s apart (transient 401 / connection / timeout).
_RPC_CONNECT_ATTEMPTS = 3
_RPC_CONNECT_DELAY_SEC = 1.0
_RPC_CHAIN_LOGGED = False
logger = logging.getLogger(__name__)


def default_json_rpc_url() -> List[str]:
    """Ordered Polygon JSON-RPC URLs: env-configured endpoints first, then public fallbacks."""
    out: List[str] = []
    for endpoint in RPC_ENDPOINTS:
        e = str(endpoint).strip()
        if e and e not in out:
            out.append(e)
    for endpoint in RPC_FALLBACKS:
        e = str(endpoint).strip()
        if e and e not in out:
            out.append(e)
    primary = RPC or RPC_URL or WEB3_PROVIDER_URI
    p = str(primary).strip()
    if p and p not in out:
        out.append(p)
    for url in _DEFAULT_POLYGON_PUBLIC_RPCS:
        if url not in out:
            out.append(url)
    return out


def _connect_one(endpoint: str, *, timeout: int) -> Any:
    """Build Web3, verify with ``eth.block_number``; retries on transient HTTP/network errors."""
    from requests.exceptions import RequestException
    from web3 import Web3

    endpoint = endpoint.strip()
    last_exc: Exception | None = None
    for attempt in range(_RPC_CONNECT_ATTEMPTS):
        try:
            provider = Web3.HTTPProvider(endpoint, request_kwargs={"timeout": timeout})
            w3 = Web3(provider)
            _ = w3.eth.block_number
            return w3
        except RequestException as exc:
            last_exc = exc
            if attempt + 1 < _RPC_CONNECT_ATTEMPTS:
                time.sleep(_RPC_CONNECT_DELAY_SEC)
    assert last_exc is not None
    raise last_exc


def _log_rpc_chain_once(chain: Sequence[str]) -> None:
    """Emit resolved RPC chain once per process for easier ops debugging."""
    global _RPC_CHAIN_LOGGED
    if _RPC_CHAIN_LOGGED:
        return
    _RPC_CHAIN_LOGGED = True
    rendered = " -> ".join(str(url).strip() for url in chain if str(url).strip())
    logger.info("Resolved RPC endpoint chain (%d): %s", len(chain), rendered)


def connect_web3(
    *,
    urls: Sequence[str] | None = None,
    explicit_rpc: str | None = None,
    timeout: int = 30,
) -> Any:
    """Connect to the first reachable Polygon RPC, trying fallbacks after exhausting retries."""
    if urls is not None:
        chain = [str(u).strip() for u in urls if isinstance(u, str) and str(u).strip()]
    elif explicit_rpc and str(explicit_rpc).strip():
        e = explicit_rpc.strip()
        chain = [e, *[u for u in default_json_rpc_url() if u != e]]
    else:
        chain = list(default_json_rpc_url())
    if not chain:
        chain = list(_DEFAULT_POLYGON_PUBLIC_RPCS)
    _log_rpc_chain_once(chain)

    last_exc: Exception | None = None
    for endpoint in chain:
        try:
            return _connect_one(endpoint, timeout=timeout)
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"All RPC endpoints failed (tried {len(chain)})") from last_exc


@dataclass
class XSignalConfig:
    TIER_HIGH_MIN: float = X_SIGNAL_DYNAMIC_TIER_HIGH_MIN
    USDC_GTE_TIER_HIGH: float = X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH
    USDC_GTE_FORCE_ELIGIBLE: float = X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE
    USDC_BELOW_FORCE_ELIGIBLE: float = X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE
    COOLDOWN_SECONDS: int = 1800
    TP_PERCENT: float = 0.12


# Global instance (everyone imports this)
X_SIGNAL = XSignalConfig()

# Other future configs can be added here (e.g. ProtectionConfig, CopyTradeConfig)

# Legacy alias for backward compatibility
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = 0.75
