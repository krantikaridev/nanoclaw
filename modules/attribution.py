"""Structured per-trade logging for post-hoc attribution (PnL vs gas vs strategy path)."""

from __future__ import annotations

import os
from typing import Any


def normalize_tx_hex(tx_hash: Any) -> str:
    if tx_hash is None:
        return ""
    if isinstance(tx_hash, (bytes, bytearray)):
        try:
            return "0x" + tx_hash.hex()
        except Exception:
            return ""
    if hasattr(tx_hash, "hex"):
        hx = tx_hash.hex
        try:
            out = hx() if callable(hx) else str(hx)
        except Exception:
            out = str(tx_hash)
        return out if out.startswith("0x") else ("0x" + out.removeprefix("0x") if out else "")
    s = str(tx_hash).strip()
    return s if s.startswith("0x") else ("0x" + s.removeprefix("0x") if s else "")


def log_trade_attribution(
    *,
    tx_hash_hex: str,
    direction: str | None,
    amount_in: int,
    trade_size: float,
    message: str,
) -> None:
    """Emit a deterministic single-line attribution record (operators may grep real_cron.log)."""
    if os.getenv("NANOCLAW_TRADE_ATTRIBUTION", "true").lower() not in ("1", "true", "yes"):
        return
    path = direction or ""
    amt = trade_size if trade_size else float(amount_in)
    clipped = " ".join((message or "").split())[:500]
    print(
        "[nanoclaw] TRADE_ATTRIBUTION "
        f"tx={tx_hash_hex or 'pending'} dir={path} sz≈{amt:.6g} msg={clipped}",
        flush=True,
    )


def notify_swap_success(*, decision: Any, tx_hash: Any) -> None:
    """Hook after an on-chain swap receipt is known."""
    from . import agent_layer

    hexed = normalize_tx_hex(tx_hash)
    log_trade_attribution(
        tx_hash_hex=hexed,
        direction=getattr(decision, "direction", None),
        amount_in=int(getattr(decision, "amount_in", 0)),
        trade_size=float(getattr(decision, "trade_size", 0.0)),
        message=str(getattr(decision, "message", "") or ""),
    )
    agent_layer.maybe_post_trade_digest(
        direction=getattr(decision, "direction", None),
        amount_in=int(getattr(decision, "amount_in", 0)),
        message=str(getattr(decision, "message", "") or ""),
        tx_hash_repr=hexed or repr(tx_hash),
    )

