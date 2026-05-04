"""Reusable 1inch API helpers.

The swap executor keeps thin local wrappers for backward compatibility with tests,
while this module owns request/response details and payload shaping.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


def oneinch_headers(api_key: str) -> dict[str, str]:
    """Build auth headers for 1inch HTTP APIs."""
    if not api_key:
        raise ValueError("Missing ONEINCH_API_KEY (required for 1inch swap API)")
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def oneinch_get_json(*, url: str, api_key: str) -> dict:
    """Fetch and decode a JSON object from the 1inch API."""
    req = urllib.request.Request(url=url, headers=oneinch_headers(api_key), method="GET")
    with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310
        payload = response.read().decode("utf-8")
    data = json.loads(payload or "{}")
    if not isinstance(data, dict):
        raise ValueError("Invalid 1inch response format")
    return data


def oneinch_approve_spender(*, spender_endpoint: str, api_key: str) -> str:
    """Resolve spender address used by 1inch for token approvals."""
    data = oneinch_get_json(url=spender_endpoint, api_key=api_key)
    spender = str(data.get("address", "")).strip()
    if not spender:
        raise ValueError("1inch approve/spender response missing address")
    return spender


def oneinch_swap_payload(
    *,
    swap_endpoint: str,
    api_key: str,
    wallet: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    default_slippage_bps: int,
    swap_slippage_bps: int | None = None,
) -> dict:
    """Build and request a swap quote+tx payload from 1inch."""
    bps = int(default_slippage_bps) if swap_slippage_bps is None else int(swap_slippage_bps)
    slippage_percent = max(0.1, float(bps) / 100.0)
    params = {
        "src": token_in,
        "dst": token_out,
        "amount": str(int(amount_in)),
        "from": wallet,
        "origin": wallet,
        "receiver": wallet,
        "slippage": f"{slippage_percent:.2f}",
        "disableEstimate": "false",
        "allowPartialFill": "false",
    }
    query = urllib.parse.urlencode(params)
    url = f"{swap_endpoint}?{query}"
    data = oneinch_get_json(url=url, api_key=api_key)
    tx_data = data.get("tx")
    if not isinstance(tx_data, dict) or not tx_data.get("to") or not tx_data.get("data"):
        raise ValueError("1inch swap response missing tx payload")
    return data
