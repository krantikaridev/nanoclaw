from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
try:
    from web3 import Web3
except ImportError:  # pragma: no cover - optional in lightweight test environments
    Web3 = object  # type: ignore[assignment]

load_dotenv()


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


# Log prefix for actionable lines (set empty to omit).
LOG_PREFIX = os.getenv("LOG_PREFIX", "[nanoclaw]").strip()

# Native POL floor for gas (used by multiple modules; can be overridden via env MIN_POL_FOR_GAS).
MIN_POL_FOR_GAS = float(os.getenv("MIN_POL_FOR_GAS", "0.005"))

# Deployment-specific addresses should be env-driven.
WALLET = os.getenv("WALLET", "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA")
USDT = os.getenv("USDT", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F")
USDC = os.getenv("USDC", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
WMATIC = os.getenv("WMATIC", "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270")
ROUTER = os.getenv("ROUTER", "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")

# Tokenized equities (placeholders; set real addresses in .env)
GOOGLON = os.getenv("GOOGLON", "")
MSFTON = os.getenv("MSFTON", "")
APPLON = os.getenv("APPLON", "")
AMZNON = os.getenv("AMZNON", "")

# ABIs are versioned protocol definitions. Keep defaults in-repo, but allow env overrides.
ERC20_ABI_PATH = os.getenv("ERC20_ABI_PATH", _default_abi_path("nanoclaw/abi/erc20.json"))
ROUTER_ABI_PATH = os.getenv(
    "ROUTER_ABI_PATH",
    _default_abi_path("nanoclaw/abi/router_swap_exact_tokens_for_tokens.json"),
)
GET_AMOUNTS_OUT_ABI_PATH = os.getenv(
    "GET_AMOUNTS_OUT_ABI_PATH",
    _default_abi_path("nanoclaw/abi/router_get_amounts_out.json"),
)

ERC20_ABI = _load_json(ERC20_ABI_PATH)
ROUTER_ABI = _load_json(ROUTER_ABI_PATH)
GET_AMOUNTS_OUT_ABI = _load_json(GET_AMOUNTS_OUT_ABI_PATH)

# Combined QuickSwap/Uniswap V2 Router (swap + getAmountsOut on Polygon).
_ROUTER_AMOUNT_OUT_ENTRIES: list = _abi_fragment_to_entry_list(GET_AMOUNTS_OUT_ABI)
ROUTER_SWAP_AND_QUOTE_ABI: list = list(ROUTER_ABI) + _ROUTER_AMOUNT_OUT_ENTRIES
