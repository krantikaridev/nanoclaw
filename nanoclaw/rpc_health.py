"""Polygon PoS RPC connectivity check (operator / nanoup hook)."""

from __future__ import annotations

# Repository assumes Polygon PoS mainnet for stage; Amoy et al. remain out of scope here.
EXPECTED_POLYGON_POS_CHAIN_ID = 137


def check_polygon_pos_rpc(*, timeout: int = 30) -> tuple[bool, str]:
    """Return ``(ok, message)`` after a real ``eth.blockNumber`` via ``connect_web3()``."""
    try:
        from nanoclaw.config import connect_web3
    except Exception as exc:  # pragma: no cover - import guard
        return False, f"import error: {exc}"

    try:
        w3 = connect_web3(timeout=timeout)
    except Exception as exc:
        return False, f"RPC connect failed: {exc}"

    try:
        chain_id = int(w3.eth.chain_id)
    except Exception as exc:
        return False, f"chain_id read failed: {exc}"

    if chain_id != EXPECTED_POLYGON_POS_CHAIN_ID:
        return (
            False,
            f"wrong chain_id={chain_id} (expected {EXPECTED_POLYGON_POS_CHAIN_ID} Polygon PoS)",
        )

    try:
        block = int(w3.eth.block_number)
    except Exception as exc:
        return False, f"block_number read failed: {exc}"

    return True, f"ok chain_id={chain_id} block={block}"
