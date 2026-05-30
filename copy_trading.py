"""
Copy-trade wallet list loader (polycopy / USDC copy path).

``followed_wallets.json`` must list **EOA trader wallets**, not Polygon token contracts.
Audit: ``python scripts/copy_trading_audit.py`` or ``nanocopyaudit`` — see ``docs/COPY_TRADING_AUDIT.md``.
"""
import json
import os

import config as cfg
from config import DEFAULT_MAX_COPY_RATIO
from modules.copy_trading_audit import filter_tradeable_wallets

CONFIG_FILE = "followed_wallets.json"

_DEFAULT_MAX_COPY_RATIO = DEFAULT_MAX_COPY_RATIO
_warned_misconfig = False


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"wallets": [], "max_copy_ratio": _DEFAULT_MAX_COPY_RATIO, "enabled": True}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def _maybe_warn_misconfig(raw: list[str], tradeable: list[str]) -> None:
    global _warned_misconfig
    if _warned_misconfig or len(raw) == len(tradeable):
        return
    _warned_misconfig = True
    dropped = len(raw) - len(tradeable)
    print(
        f"⚠️ [COPY] followed_wallets.json: rejected {dropped} non-tradeable "
        f"address(es) (token contracts?). Run: python scripts/copy_trading_audit.py"
    )


def get_target_wallets():
    raw = load_config().get("wallets", [])
    if not isinstance(raw, list):
        raw = []
    reject = bool(getattr(cfg, "COPY_TRADING_REJECT_TOKEN_CONTRACTS", True))
    tradeable = filter_tradeable_wallets(raw, reject_token_contracts=reject)
    _maybe_warn_misconfig(raw, tradeable)
    return tradeable


def get_copy_ratio():
    return load_config().get("max_copy_ratio", _DEFAULT_MAX_COPY_RATIO)


def should_copy_trade(tx_data):
    print("📡 [COPY] Opportunity detected — executing small test trade (20% allocation)")
    return True
