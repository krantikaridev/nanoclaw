"""Per-endpoint Polygon JSON-RPC probe (operator diagnostics / alerts)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from nanoclaw.rpc_health import EXPECTED_POLYGON_POS_CHAIN_ID

_KEY_IN_URL_RE = re.compile(r"(/polygon/)([a-fA-F0-9]{32,64})(?=/?|$)")


def redact_rpc_url(url: str) -> str:
    """Hide API key segments in RPC URLs for logs and Telegram."""
    u = str(url).strip()
    if not u:
        return u
    return _KEY_IN_URL_RE.sub(r"\1***", u)


@dataclass(frozen=True)
class RpcEndpointProbe:
    url: str
    ok: bool
    chain_id: int | None
    block_number: int | None
    latency_ms: float | None
    error: str | None

    @property
    def display_url(self) -> str:
        return redact_rpc_url(self.url)


def probe_rpc_endpoint(url: str, *, timeout: int = 12) -> RpcEndpointProbe:
    """Single JSON-RPC probe: ``eth_chainId`` + ``eth_blockNumber``."""
    import time

    from requests.exceptions import RequestException
    from web3 import Web3

    endpoint = str(url).strip()
    if not endpoint:
        return RpcEndpointProbe(
            url=endpoint,
            ok=False,
            chain_id=None,
            block_number=None,
            latency_ms=None,
            error="empty url",
        )
    started = time.perf_counter()
    try:
        provider = Web3.HTTPProvider(endpoint, request_kwargs={"timeout": timeout})
        w3 = Web3(provider)
        chain_id = int(w3.eth.chain_id)
        block = int(w3.eth.block_number)
        latency_ms = (time.perf_counter() - started) * 1000.0
        if chain_id != EXPECTED_POLYGON_POS_CHAIN_ID:
            return RpcEndpointProbe(
                url=endpoint,
                ok=False,
                chain_id=chain_id,
                block_number=block,
                latency_ms=latency_ms,
                error=f"wrong chain_id={chain_id} (expected {EXPECTED_POLYGON_POS_CHAIN_ID})",
            )
        return RpcEndpointProbe(
            url=endpoint,
            ok=True,
            chain_id=chain_id,
            block_number=block,
            latency_ms=latency_ms,
            error=None,
        )
    except RequestException as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RpcEndpointProbe(
            url=endpoint,
            ok=False,
            chain_id=None,
            block_number=None,
            latency_ms=latency_ms,
            error=str(exc),
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RpcEndpointProbe(
            url=endpoint,
            ok=False,
            chain_id=None,
            block_number=None,
            latency_ms=latency_ms,
            error=str(exc),
        )


def probe_rpc_chain(
    endpoints: Sequence[str],
    *,
    timeout: int = 12,
) -> list[RpcEndpointProbe]:
    seen: set[str] = set()
    out: list[RpcEndpointProbe] = []
    for raw in endpoints:
        url = str(raw).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(probe_rpc_endpoint(url, timeout=timeout))
    return out


def probe_configured_endpoints(*, timeout: int = 12) -> list[RpcEndpointProbe]:
    from nanoclaw.config import default_json_rpc_url

    return probe_rpc_chain(default_json_rpc_url(), timeout=timeout)


def any_endpoint_healthy(probes: Sequence[RpcEndpointProbe]) -> bool:
    return any(p.ok for p in probes)


def format_probe_report(probes: Sequence[RpcEndpointProbe]) -> str:
    lines: list[str] = []
    healthy = sum(1 for p in probes if p.ok)
    lines.append(f"RPC probe: {healthy}/{len(probes)} healthy")
    for p in probes:
        if p.ok:
            lat = f"{p.latency_ms:.0f}ms" if p.latency_ms is not None else "n/a"
            lines.append(
                f"  OK  {p.display_url} | chain={p.chain_id} block={p.block_number} {lat}"
            )
        else:
            err = (p.error or "unknown").replace("\n", " ")[:160]
            lines.append(f"  FAIL {p.display_url} | {err}")
    return "\n".join(lines)
