from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:
    from web3 import Web3
except ImportError:  # pragma: no cover - optional in lightweight test environments
    Web3 = object  # type: ignore[assignment]

import config as cfg


def _load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _default_abi_path(relative_to_repo: str) -> str:
    repo_root = Path(__file__).resolve().parent
    return str(repo_root / relative_to_repo)


def _abi_fragment_to_entry_list(fragment: object) -> list:
    """Normalize JSON-loaded ABI snippets for web3.eth.contract ABI=.

    - In-repo router JSON lists are `[{...}]` (already a proper list fragment).
    - Some contract ABIs expose a single function as `{...}` dict without an outer array.
    - Never wrap an existing list in another `[...]` — that would nest `[[{...}]]` and break calls.
    """
    if fragment is None:
        return []
    if isinstance(fragment, dict):
        return [fragment]
    if isinstance(fragment, (list, tuple)):
        return list(fragment)
    return []


# X-signal per-asset cooldown should remain env-driven, never hardcoded.
LOG_PREFIX = cfg.LOG_PREFIX
MIN_POL_FOR_GAS = cfg.MIN_POL_FOR_GAS
PER_ASSET_COOLDOWN_MINUTES = cfg.PER_ASSET_COOLDOWN_MINUTES
PER_ASSET_COOLDOWN_SECONDS = PER_ASSET_COOLDOWN_MINUTES * 60
WALLET = cfg.WALLET
USDT = cfg.USDT
USDC = cfg.USDC
USDC_NATIVE = cfg.USDC_NATIVE
WMATIC = cfg.WMATIC
ROUTER = cfg.ROUTER
GOOGLON = cfg.GOOGLON
MSFTON = cfg.MSFTON
APPLON = cfg.APPLON
AMZNON = cfg.AMZNON


@dataclass(frozen=True)
class PolygonAddresses:
    """Single bundle for Polygon routing — prefer `POLYGON` for new code; module-level names remain for imports/tests."""

    wallet: str
    usdt: str
    usdc: str
    wmatic: str
    router: str


POLYGON = PolygonAddresses(
    wallet=WALLET,
    usdt=USDT,
    usdc=USDC,
    wmatic=WMATIC,
    router=ROUTER,
)

# ABIs are versioned protocol definitions. Keep defaults in-repo, but allow env overrides.
ERC20_ABI_PATH = cfg.env_str("ERC20_ABI_PATH", _default_abi_path("nanoclaw/abi/erc20.json"))
ROUTER_ABI_PATH = cfg.env_str(
    "ROUTER_ABI_PATH",
    _default_abi_path("nanoclaw/abi/router_swap_exact_tokens_for_tokens.json"),
)
GET_AMOUNTS_OUT_ABI_PATH = cfg.env_str(
    "GET_AMOUNTS_OUT_ABI_PATH",
    _default_abi_path("nanoclaw/abi/router_get_amounts_out.json"),
)

ERC20_ABI = _load_json(ERC20_ABI_PATH)
ROUTER_ABI = _load_json(ROUTER_ABI_PATH)
GET_AMOUNTS_OUT_ABI = _load_json(GET_AMOUNTS_OUT_ABI_PATH)

# Combined QuickSwap/Uniswap V2 Router (swap + getAmountsOut on Polygon).
_ROUTER_AMOUNT_OUT_ENTRIES: list = _abi_fragment_to_entry_list(GET_AMOUNTS_OUT_ABI)
ROUTER_SWAP_AND_QUOTE_ABI: list = list(ROUTER_ABI) + _ROUTER_AMOUNT_OUT_ENTRIES
