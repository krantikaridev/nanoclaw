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

# Per-endpoint: first attempt + retries, 1s apart (transient 401 / connection / timeout).
_RPC_CONNECT_ATTEMPTS = 3
_RPC_CONNECT_DELAY_SEC = 1.0
_RPC_CHAIN_LOGGED = False

# Process-wide endpoint health: avoid rotating away from good RPCs on transient blips.
_RPC_FAILURES_BEFORE_COOLDOWN = 3
_RPC_ENDPOINT_COOLDOWN_SEC = 20.0
_RPC_STICKY_PREFER_SECONDS = 600.0
_RPC_RECOVERY_PASS_DELAY_SEC = 2.0
RPC_RECOVERY_PASS_DELAY_SEC = _RPC_RECOVERY_PASS_DELAY_SEC

_RPC_LAST_SUCCESS: str | None = None
_RPC_LAST_SUCCESS_TS: float = 0.0
_RPC_ENDPOINT_FAILURE_STREAK: dict[str, int] = {}
_RPC_ENDPOINT_COOLDOWN_UNTIL: dict[str, float] = {}

logger = logging.getLogger(__name__)


def _normalize_rpc_endpoint(url: str) -> str:
    return str(url).strip()


def _dedupe_rpc_endpoints(endpoints: Sequence[str]) -> list[str]:
    out: list[str] = []
    for endpoint in endpoints:
        normalized = _normalize_rpc_endpoint(endpoint)
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def record_rpc_success(endpoint: str) -> None:
    """Remember last good endpoint and clear its failure/cooldown state."""
    global _RPC_LAST_SUCCESS, _RPC_LAST_SUCCESS_TS
    ep = _normalize_rpc_endpoint(endpoint)
    if not ep:
        return
    _RPC_LAST_SUCCESS = ep
    _RPC_LAST_SUCCESS_TS = time.time()
    _RPC_ENDPOINT_FAILURE_STREAK.pop(ep, None)
    _RPC_ENDPOINT_COOLDOWN_UNTIL.pop(ep, None)


def record_rpc_failure(endpoint: str) -> None:
    """Count consecutive failures; short cooldown only after several misses."""
    ep = _normalize_rpc_endpoint(endpoint)
    if not ep:
        return
    streak = int(_RPC_ENDPOINT_FAILURE_STREAK.get(ep, 0)) + 1
    _RPC_ENDPOINT_FAILURE_STREAK[ep] = streak
    if streak >= _RPC_FAILURES_BEFORE_COOLDOWN:
        until = time.time() + float(_RPC_ENDPOINT_COOLDOWN_SEC)
        _RPC_ENDPOINT_COOLDOWN_UNTIL[ep] = until
        _RPC_ENDPOINT_FAILURE_STREAK[ep] = 0
        logger.warning(
            "RPC endpoint entering short cooldown (%ds) after %d failures: %s",
            int(_RPC_ENDPOINT_COOLDOWN_SEC),
            _RPC_FAILURES_BEFORE_COOLDOWN,
            ep,
        )


def rpc_endpoint_in_cooldown(endpoint: str, *, now: float | None = None) -> bool:
    ep = _normalize_rpc_endpoint(endpoint)
    if not ep:
        return False
    ts = float(_RPC_ENDPOINT_COOLDOWN_UNTIL.get(ep, 0.0) or 0.0)
    if ts <= 0.0:
        return False
    current = time.time() if now is None else float(now)
    if current >= ts:
        _RPC_ENDPOINT_COOLDOWN_UNTIL.pop(ep, None)
        return False
    return True


def last_successful_rpc() -> str | None:
    return _RPC_LAST_SUCCESS


def order_rpc_endpoints(chain: Sequence[str]) -> list[str]:
    """Prefer last successful RPC; deprioritize endpoints in short cooldown."""
    normalized = _dedupe_rpc_endpoints(chain)
    if not normalized:
        return []

    now = time.time()
    ready: list[str] = []
    cooling: list[str] = []
    for endpoint in normalized:
        if rpc_endpoint_in_cooldown(endpoint, now=now):
            cooling.append(endpoint)
        else:
            ready.append(endpoint)

    sticky = _RPC_LAST_SUCCESS
    prefer_sticky = (
        sticky
        and sticky in ready
        and (now - float(_RPC_LAST_SUCCESS_TS or 0.0)) < float(_RPC_STICKY_PREFER_SECONDS)
    )
    if prefer_sticky:
        ready = [sticky, *[e for e in ready if e != sticky]]

    ordered = ready + [e for e in cooling if e not in ready]
    return ordered


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
        except Exception as exc:
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


def _try_connect_chain(chain: Sequence[str], *, timeout: int, recovery_pass: bool) -> Any:
    ordered = order_rpc_endpoints(chain) if not recovery_pass else _dedupe_rpc_endpoints(chain)
    last_exc: Exception | None = None
    for endpoint in ordered:
        if not recovery_pass and rpc_endpoint_in_cooldown(endpoint):
            logger.info("RPC skip (cooldown active): %s", endpoint)
            continue
        try:
            client = _connect_one(endpoint, timeout=timeout)
            record_rpc_success(endpoint)
            if recovery_pass:
                logger.info("RPC recovery pass succeeded: %s", endpoint)
            return client
        except Exception as exc:
            if not recovery_pass:
                record_rpc_failure(endpoint)
            last_exc = exc
            logger.warning(
                "RPC connect failed (%d attempts): %s | %s",
                _RPC_CONNECT_ATTEMPTS,
                endpoint,
                exc,
            )
            continue
    raise RuntimeError(f"RPC chain pass failed (endpoints={len(ordered)})") from last_exc


def connect_web3(
    *,
    urls: Sequence[str] | None = None,
    explicit_rpc: str | None = None,
    timeout: int = 30,
) -> Any:
    """Connect to Polygon RPC with sticky preference, cooldowns, and a patient recovery pass."""
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
    try:
        return _try_connect_chain(chain, timeout=timeout, recovery_pass=False)
    except Exception as exc:
        last_exc = exc

    logger.warning(
        "All ready RPC endpoints failed; recovery pass in %.1fs (sticky=%s)",
        _RPC_RECOVERY_PASS_DELAY_SEC,
        last_successful_rpc() or "none",
    )
    time.sleep(_RPC_RECOVERY_PASS_DELAY_SEC)
    try:
        return _try_connect_chain(chain, timeout=timeout, recovery_pass=True)
    except Exception as exc:
        last_exc = exc

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

# Legacy alias for backward compatibility
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = 0.75
