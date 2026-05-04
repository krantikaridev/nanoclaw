"""Optional Grok (xAI) + Telegram diagnostics — observability-first; swaps stay canonical unless opted in."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from config import (
    GROK_API_BASE,
    GROK_API_KEY,
    GROK_MODEL,
    NANOCLAW_AGENT_CAN_OVERRIDE_SWAP,
    NANOCLAW_AGENT_LAYER_ADVISORY,
    NANOCLAW_AGENT_LAYER_ENABLED,
    NANOCLAW_GROK_ENABLED,
    NANOCLAW_TELEMETRY_TELEGRAM,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
logger = logging.getLogger(__name__)

def _telegram_send_html(text: str) -> None:
    token = TELEGRAM_BOT_TOKEN
    chat = TELEGRAM_CHAT_ID
    if not token or not chat:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat, "text": text[:3900], "disable_web_page_preview": True},
        separators=(",", ":"),
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=12)  # noqa: S310 — operator-owned endpoint
    except urllib.error.HTTPError as e:
        logger.debug("telegram_http_error=%s", e)


def grok_chat_advisory(prompt: str) -> str | None:
    """Call xAI Grok-compatible chat endpoint when configured; never raises to caller."""
    if not NANOCLAW_GROK_ENABLED:
        return None
    key = GROK_API_KEY
    if not key:
        return None
    base = GROK_API_BASE.rstrip("/")
    model = GROK_MODEL
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt[:12000]}],
            "temperature": 0,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        choices = body.get("choices") or []
        msg = (((choices[0] or {}).get("message")) or {}).get("content")
        return (msg or "").strip() or None
    except Exception:
        logger.exception("grok_chat_advisory_failed")
        return None


def grok_agent_decision(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Backward-compatible helper name: advisory JSON blob (no enforced schema)."""
    if not summary:
        return None
    if not NANOCLAW_AGENT_LAYER_ADVISORY:
        return None
    prompt = (
        "Respond with one terse sentence of risk commentary for this trading bot snapshot:\n"
        f"{json.dumps(summary, separators=(',', ':'), default=str)[:6000]}"
    )
    text = grok_chat_advisory(prompt)
    return {"note": text} if text else None


def maybe_post_trade_digest(
    *,
    direction: str | None,
    amount_in: int,
    message: str,
    tx_hash_repr: str,
) -> None:
    """Fire-and-forget Telegram status + optional Grok advisory after a mined swap."""
    if not (NANOCLAW_AGENT_LAYER_ENABLED or NANOCLAW_TELEMETRY_TELEGRAM):
        return
    headline = (
        f"<b>[nanoclaw]</b> swap ok\n"
        f"dir={(direction or '').strip()} amount_in={amount_in}\n"
        f"tx={tx_hash_repr.strip()}"
    )
    _telegram_send_html(headline[:3900])


def optionally_merge_agent_override(
    decision: Any,
    *,
    advisory: dict[str, Any] | None,
) -> Any:
    """Reserved: off by default (`NANOCLAW_AGENT_CAN_OVERRIDE_SWAP` must be set)."""
    if not advisory or not NANOCLAW_AGENT_CAN_OVERRIDE_SWAP:
        return decision
    # Intentionally empty guard rail — overrides require an explicit approved schema later.
    return decision
