import asyncio
import time
import urllib.error
from dataclasses import dataclass
from typing import Literal

from web3 import Web3

import config as cfg
from config import (
    FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS_RAW,
    FALLBACK_ROUTER_SLIPPAGE_BPS_RAW,
    HIGH_CONVICTION_FALLBACK_PRIMARY_BPS,
    HIGH_CONVICTION_FALLBACK_RETRY_BPS,
    ONEINCH_API_KEY,
    ONEINCH_SPENDER_ENDPOINT,
    ONEINCH_SWAP_ENDPOINT,
    ONCHAIN_SWAP_RETRY_EXTRA_BPS,
    SWAP_SLIPPAGE_BPS,
    UNISWAP_V3_QUOTER,
    UNISWAP_V3_QUOTER_V2,
    UNISWAP_V3_SWAP_ROUTER,
)
from constants import (
    LOG_PREFIX,
    ROUTER,
    ROUTER_SWAP_AND_QUOTE_ABI,
    USDC,
    WALLET,
    USDT,
    WMATIC,
)
from nanoclaw.abi.uniswap_v3_abi import UNISWAP_V3_QUOTER_ABI, UNISWAP_V3_ROUTER_ABI
from nanoclaw.execution.uniswap_v3_helpers import (
    ensure_erc20_allowance,
    quote_exact_input_single,
    quote_exact_input_single_quoterv2,
    resolve_spendable_usdc_token,
)
from nanoclaw.execution.oneinch_helpers import oneinch_approve_spender, oneinch_swap_payload

# When 1inch is skipped or fails, router quoting uses higher slippage than SWAP_SLIPPAGE_BPS.
# Optional overrides; otherwise derived from base slippage (see ``_fallback_router_slippage_bps``).
# +0.5% default: one on-chain retry bumps slippage by this many bps (1inch + router fallback).

_prefix = LOG_PREFIX + " " if LOG_PREFIX else ""


_FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS = 600
ROUTER = Web3.to_checksum_address(ROUTER)
UNISWAP_V3_ROUTER = Web3.to_checksum_address(UNISWAP_V3_SWAP_ROUTER)
UNISWAP_V3_QUOTER = Web3.to_checksum_address(UNISWAP_V3_QUOTER)

def _erc20_allowance(w3, token_address: str, owner: str, spender: str) -> int:
    token = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=[
            {
                "constant": True,
                "inputs": [
                    {"name": "_owner", "type": "address"},
                    {"name": "_spender", "type": "address"},
                ],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function",
            }
        ],
    )
    return int(token.functions.allowance(
        Web3.to_checksum_address(owner),
        Web3.to_checksum_address(spender),
    ).call())


def ensure_startup_router_approval(
    w3,
    private_key,
    router_address,
    token_address="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    *,
    force: bool = False,
    min_allowance: int = 10**24,
) -> bool:
    """Ensure router ERC20 allowance; skip when sufficient or POL too low (never crash startup)."""
    from web3 import Web3

    account = w3.eth.account.from_key(private_key)
    wallet = account.address
    router = Web3.to_checksum_address(router_address)
    token_addr = Web3.to_checksum_address(token_address)
    allowance = _erc20_allowance(w3, token_addr, wallet, router)
    if not force and allowance >= int(min_allowance):
        print(
            f"[FORCE-MAX-APPROVE] Skipped — allowance sufficient "
            f"(allowance={allowance}, min={min_allowance})"
        )
        return True

    approve_gas_units = int(getattr(cfg, "POL_APPROVE_GAS_UNITS", 85_000))
    gas_price = int(w3.eth.gas_price)
    pol_balance = float(w3.from_wei(w3.eth.get_balance(wallet), "ether"))
    approve_cost_pol = (approve_gas_units * gas_price / 1e18) * 1.10
    if pol_balance + 1e-12 < approve_cost_pol:
        print(
            f"[FORCE-MAX-APPROVE] Skipped — insufficient POL for approve "
            f"(pol≈{pol_balance:.6f}, need≈{approve_cost_pol:.6f})"
        )
        return False

    token = w3.eth.contract(
        address=token_addr,
        abi=[
            {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"},
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function",
            }
        ],
    )
    max_uint = (1 << 256) - 1
    print(f"[FORCE-MAX-APPROVE] Forcing fresh MAX approval for router {router_address}")
    tx = token.functions.approve(router, max_uint).build_transaction({
        "from": wallet,
        "nonce": w3.eth.get_transaction_count(wallet),
        "gas": approve_gas_units,
        "gasPrice": gas_price,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"[FORCE-MAX-APPROVE] Sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status == 1:
        time.sleep(8)
        print("[FORCE-MAX-APPROVE] ✅ Fresh MAX confirmed + fully propagated (ready for swap)")
        return True
    print("[FORCE-MAX-APPROVE] ❌ Approval tx failed")
    return False


def _force_max_approval(w3, private_key, router_address, token_address="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"):
    """Backward-compatible wrapper — prefer ``ensure_startup_router_approval``.

    Historical default passed ``force=True`` which bypassed the allowance pre-check
    inside ``ensure_startup_router_approval``. On 2026-05-24 the live bot crash-looped
    on startup when POL ≈0.025 < approve gas budget; allowance was already MAX, so
    the safe path is to skip rather than force a fresh approve. The wrapper now
    delegates without ``force`` so both the allowance and POL pre-checks apply,
    matching the new call site in ``clean_swap.py`` (``ensure_startup_router_approval``).
    """
    return ensure_startup_router_approval(
        w3,
        private_key,
        router_address,
        token_address=token_address,
    )

def _fallback_router_slippage_bps() -> int:
    """Slippage for QuickSwap-style router when 1inch is not used (typically looser than primary)."""
    if FALLBACK_ROUTER_SLIPPAGE_BPS_RAW:
        return max(int(FALLBACK_ROUTER_SLIPPAGE_BPS_RAW), _FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS)
    return max(SWAP_SLIPPAGE_BPS + 150, 250, _FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS)

def _fallback_router_retry_slippage_bps(primary_bps: int) -> int:
    """Second attempt after an on-chain revert; +ONCHAIN_SWAP_RETRY_EXTRA_BPS vs first fallback quote."""
    if FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS_RAW:
        return max(int(FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS_RAW), _FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS)
    return min(max(primary_bps + ONCHAIN_SWAP_RETRY_EXTRA_BPS, _FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS), 9999)


def _is_stf_revert_reason(reason: str) -> bool:
    """True when revert looks like Uniswap V3 STF (Too little received / slippage tolerance)."""
    if not reason:
        return False
    compact = reason.upper().replace(" ", "")
    if "STF" in compact or "TOOLITTLERECEIVED" in compact:
        return True
    # Uniswap V3 SwapRouter error selector for STF()
    return "0X3610C973" in compact or "3610C973" in compact


def _x_signal_fallback_slippage_ramp(primary_bps: int, retry_bps: int) -> list[int]:
    """CRITICAL (Signal-Driven Rotation profitability): ramp slippage for X-SIGNAL fallback router.

    Graduated steps reduce repeated STF reverts vs one large jump. Four steps when primary→retry gap ≥ 2000 bps;
    three steps when gap ≥ 300 bps; otherwise primary then retry only.
    """
    floor = _FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS
    primary = min(max(int(primary_bps), floor), 9999)
    retry = min(max(int(retry_bps), primary, floor), 9999)
    if retry <= primary:
        return [primary]
    gap = retry - primary
    if gap >= 2000:
        step2 = min(primary + gap // 3, retry - 1)
        step3 = min(primary + (2 * gap) // 3, retry - 1)
        steps = [primary]
        for s in (step2, step3):
            if s > steps[-1]:
                steps.append(s)
        if steps[-1] < retry:
            steps.append(retry)
        return steps
    if gap < 300:
        return [primary, retry]
    mid = min(primary + gap // 2, retry - 1)
    if mid <= primary:
        return [primary, retry]
    return [primary, mid, retry]


def _apply_fallback_min_out_extra_buffer(amount_out_min: int, *, extra_bps: int | None) -> int:
    """Signal-driven execution quality (May 2026): extra min_out beyond quoted slippage (X-SIGNAL)."""
    if extra_bps is None or int(extra_bps) <= 0:
        return int(amount_out_min)
    extra = min(int(extra_bps), 9999)
    return max(1, (int(amount_out_min) * (10000 - extra)) // 10000)


def _x_signal_preflight_max_quote_age_seconds() -> float:
    return max(0.0, float(getattr(cfg, "X_SIGNAL_PREFLIGHT_MAX_QUOTE_AGE_SECONDS", 8.0) or 8.0))


def _x_signal_preflight_max_gas_limit() -> int:
    return max(100_000, int(getattr(cfg, "X_SIGNAL_PREFLIGHT_MAX_GAS_LIMIT", 650000) or 650000))


def _x_signal_quote_age_seconds(quote_ts: float | None) -> float | None:
    if quote_ts is None:
        return None
    return max(0.0, time.time() - float(quote_ts))


def _x_signal_quote_stale(quote_ts: float | None) -> bool:
    """CRITICAL: stale V3 quotes cause STF — refresh before submit when older than env max age."""
    max_age = _x_signal_preflight_max_quote_age_seconds()
    if max_age <= 0:
        return False
    age = _x_signal_quote_age_seconds(quote_ts)
    return age is not None and age > max_age


def _x_signal_preflight_quote_sane(
    *,
    expected_out: int,
    amount_out_min: int,
    slippage_bps: int,
) -> tuple[bool, str]:
    """Sanity-check quoted outputs before spending gas on X-SIGNAL fallback."""
    if int(expected_out) <= 0:
        return False, "expected_out<=0"
    if int(amount_out_min) <= 0:
        return False, "min_out<=0"
    if int(amount_out_min) > int(expected_out):
        return False, f"min_out({amount_out_min})>expected({expected_out})"
    slip = min(max(int(slippage_bps), 0), 9999)
    implied_floor = max(1, (int(expected_out) * (10000 - slip)) // 10000)
    if int(amount_out_min) < implied_floor * 95 // 100:
        return False, f"min_out({amount_out_min})<<slippage_implied({implied_floor})"
    return True, "ok"


def _x_signal_preflight_gas_sane(w3, tx_for_estimate: dict) -> tuple[bool, str]:
    """eth_estimateGas guard — catches broken paths before broadcast."""
    max_gas = _x_signal_preflight_max_gas_limit()
    try:
        est = int(w3.eth.estimate_gas(tx_for_estimate))
    except Exception as ex:  # noqa: BLE001
        return False, f"gas_estimate_failed:{ex}"
    if est > max_gas:
        return False, f"gas_estimate={est}>max={max_gas}"
    if est < 50_000:
        return False, f"gas_estimate_suspiciously_low={est}"
    return True, f"gas_estimate={est}"


def _try_get_revert_reason(w3, *, tx_for_call: dict) -> str:
    """Best-effort revert extraction from eth_call for logging."""
    try:
        call_payload = {
            "from": tx_for_call.get("from"),
            "to": tx_for_call.get("to"),
            "data": tx_for_call.get("data"),
            "value": int(tx_for_call.get("value") or 0),
        }
        w3.eth.call(call_payload, "latest")
        return "unavailable (eth_call returned without revert)"
    except Exception as ex:  # noqa: BLE001
        return str(ex)


def _addr_probe(addr: str) -> str:
    cs = Web3.to_checksum_address(addr)
    return f"{cs[:10]}…{cs[-6:]}"


def _resolve_spendable_usdc_token(w3, amount_in: int) -> str:
    """Pick USDC token contract with enough spendable balance for this swap."""
    return resolve_spendable_usdc_token(
        w3,
        wallet=WALLET,
        primary_usdc=USDC,
        secondary_usdc=str(getattr(cfg, "USDC_NATIVE", "") or "").strip(),
        amount_in=int(amount_in),
        addr_probe=_addr_probe,
        log_prefix=_prefix,
    )


def _ensure_usdc_allowance(
    w3,
    resolved_key: str,
    amount_in: int,
    router_address: str,
    *,
    usdc_token_address: str,
) -> None:
    ensure_erc20_allowance(
        w3,
        token_address=usdc_token_address,
        owner=WALLET,
        spender=router_address,
        required_amount=int(amount_in),
        signer_key=resolved_key,
        chain_id=137,
        log_prefix=_prefix,
    )


def build_polygon_swap_path_candidates(token_in_checksum: str, token_out_checksum: str) -> list[list[str]]:
    """Prefer direct USDC/USDT/WMATIC routes; fall back via WMATIC or USDC as middle hop."""
    a = Web3.to_checksum_address(token_in_checksum)
    b = Web3.to_checksum_address(token_out_checksum)
    wm = Web3.to_checksum_address(WMATIC)
    uc = Web3.to_checksum_address(USDC)
    seq: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()

    def push(p: tuple[str, ...]) -> None:
        key = tuple(Web3.to_checksum_address(x) for x in p)
        if key in seen:
            return
        seen.add(key)
        seq.append(key)

    push((a, b))
    if a.lower() != wm.lower() and b.lower() != wm.lower():
        push((a, wm, b))
    if a.lower() not in (wm.lower(), uc.lower()) and b.lower() not in (wm.lower(), uc.lower()):
        push((a, uc, b))
    return [list(t) for t in seq]


def _best_quote_path(
    w3,
    *,
    router: str,
    amount_in: int,
    paths: list[list[str]],
    slippage_bps: int | None = None,
):
    slip = SWAP_SLIPPAGE_BPS if slippage_bps is None else slippage_bps
    router_cs = Web3.to_checksum_address(router)
    r = w3.eth.contract(address=router_cs, abi=ROUTER_SWAP_AND_QUOTE_ABI)

    last_err: Exception | None = None
    best_amt = 0
    best_path: list[str] | None = None

    for path in paths:
        ck = [Web3.to_checksum_address(a) for a in path]
        try:
            amounts = r.functions.getAmountsOut(amount_in, ck).call()
            out_amt = int(amounts[-1])
        except Exception as ex:  # noqa: BLE001 — pool/router may miss pair
            last_err = ex
            continue
        if out_amt > best_amt:
            best_amt = out_amt
            best_path = ck

    if best_path is None or best_amt <= 0:
        err_tail = f" Last error: {last_err!r}" if last_err else ""
        raise RuntimeError(
            "No quotable router path — check liquidity/token addresses." + err_tail
        ) from last_err

    min_out = max(1, (best_amt * (10000 - min(slip, 9999))) // 10000)
    return best_path, best_amt, min_out


def _quote_uniswap_v3_exact_input_single(
    w3,
    *,
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int,
    fee: int = 3000,
) -> tuple[int, int]:
    return quote_exact_input_single(
        w3,
        quoter_address=UNISWAP_V3_QUOTER,
        quoter_abi=UNISWAP_V3_QUOTER_ABI,
        token_in=token_in,
        token_out=token_out,
        amount_in=int(amount_in),
        slippage_bps=int(slippage_bps),
        fee=int(fee),
    )


def _quote_uniswap_v3_single_fee(
    w3,
    *,
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int,
    fee: int,
) -> tuple[int, int, str]:
    """Quote one V3 fee tier — QuoterV2 first (Polygon), then legacy QuoterV1."""
    slip = min(int(slippage_bps), 9999)
    errors: list[str] = []
    quoter_v2 = str(getattr(cfg, "UNISWAP_V3_QUOTER_V2", "") or UNISWAP_V3_QUOTER_V2 or "").strip()
    prefer_v2 = bool(getattr(cfg, "X_SIGNAL_QUOTE_PREFER_QUOTER_V2", True))
    if prefer_v2 and quoter_v2:
        try:
            amount_out = int(
                quote_exact_input_single_quoterv2(
                    w3,
                    quoter_address=quoter_v2,
                    token_in=token_in,
                    token_out=token_out,
                    amount_in=int(amount_in),
                    fee=int(fee),
                )
            )
            if amount_out > 0:
                amount_out_min = max(1, (amount_out * (10000 - slip)) // 10000)
                return amount_out, amount_out_min, "quoter_v2"
        except Exception as ex:  # noqa: BLE001
            errors.append(f"quoter_v2 fee={fee}: {type(ex).__name__}: {ex}")
    try:
        expected_out, amount_out_min = _quote_uniswap_v3_exact_input_single(
            w3,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            slippage_bps=slip,
            fee=int(fee),
        )
        return int(expected_out), int(amount_out_min), "quoter_v1"
    except Exception as ex:  # noqa: BLE001
        errors.append(f"quoter_v1 fee={fee}: {type(ex).__name__}: {ex}")
        raise RuntimeError(" | ".join(errors)) from ex


def _x_signal_fee_tier_order(amount_in: int) -> tuple[int, ...]:
    """Small USDC→equity trades: probe 0.3% pool first (common for tokenized equities)."""
    small_raw = int(getattr(cfg, "X_SIGNAL_SMALL_TRADE_USDC_RAW", 15_000_000) or 15_000_000)
    if int(amount_in) + 1 <= small_raw:
        return (3000, 500, 10000)
    return (500, 3000, 10000)


@dataclass(frozen=True)
class _FallbackQuote:
    mode: Literal["v3", "v2"]
    expected_out: int
    amount_out_min: int
    v3_fee: int = 3000
    v2_path: list[str] | None = None
    quoter: str = ""


def _quote_v2_router_best(
    w3,
    *,
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int,
) -> _FallbackQuote:
    """V2 router path quote when V3 single-hop pools are missing (common for thin equity pairs)."""
    paths = build_polygon_swap_path_candidates(token_in, token_out)
    path, best_amt, min_out = _best_quote_path(
        w3,
        router=ROUTER,
        amount_in=int(amount_in),
        paths=paths,
        slippage_bps=int(slippage_bps),
    )
    return _FallbackQuote(
        mode="v2",
        expected_out=int(best_amt),
        amount_out_min=int(min_out),
        v2_path=list(path),
        quoter="v2_router",
    )


def _quote_uniswap_v3_best_fee_single(
    w3,
    *,
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int,
    fees: tuple[int, ...] | None = None,
    prefer_stable_fee: bool = False,
    user_fee_errors: dict[int, str] | None = None,
) -> tuple[int, int, int]:
    """Pick the V3 pool fee tier with the highest quoted output (signal-driven routing quality).

    When ``prefer_stable_fee`` is True (X-SIGNAL), prefer the 0.3% (3000) pool if its quote is within
    ``X_SIGNAL_STABLE_FEE_PREFER_BPS`` of the best tier — reduces thin-pool STFs on tokenized equities.
    """
    stable_fee = 3000
    stable_prefer_bps = max(
        0,
        int(getattr(cfg, "X_SIGNAL_STABLE_FEE_PREFER_BPS", 0) or 0),
    )
    fee_tiers = fees if fees is not None else _x_signal_fee_tier_order(int(amount_in))
    quotes: dict[int, tuple[int, int, str]] = {}
    last_err: Exception | None = None
    for fee in fee_tiers:
        try:
            expected_out, amount_out_min, quoter = _quote_uniswap_v3_single_fee(
                w3,
                token_in=token_in,
                token_out=token_out,
                amount_in=amount_in,
                slippage_bps=slippage_bps,
                fee=int(fee),
            )
        except Exception as ex:  # noqa: BLE001
            last_err = ex
            if user_fee_errors is not None:
                user_fee_errors[int(fee)] = str(ex)
            continue
        quotes[int(fee)] = (int(expected_out), int(amount_out_min), str(quoter))
    if not quotes:
        if last_err is not None:
            raise last_err
        raise RuntimeError("No quotable Uniswap V3 single-hop pool for fee tiers tried")
    best_fee = max(quotes, key=lambda f: quotes[f][0])
    best_out, best_min, _best_quoter = quotes[best_fee]
    if (
        prefer_stable_fee
        and stable_prefer_bps > 0
        and stable_fee in quotes
        and best_out > 0
    ):
        stable_out, stable_min, _stable_quoter = quotes[stable_fee]
        floor_out = (best_out * (10000 - stable_prefer_bps)) // 10000
        if stable_out >= floor_out:
            return stable_fee, stable_out, stable_min
    return best_fee, best_out, best_min


def _x_signal_quote_best_route(
    w3,
    *,
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int,
    prefer_stable_fee: bool = True,
) -> _FallbackQuote:
    """X-SIGNAL quote: V3 single-hop (QuoterV2→V1) then optional V2 router multihop."""
    fee_errors: dict[int, str] = {}
    try:
        fee_pick, eq, mq = _quote_uniswap_v3_best_fee_single(
            w3,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            slippage_bps=slippage_bps,
            prefer_stable_fee=prefer_stable_fee,
            user_fee_errors=fee_errors,
        )
        return _FallbackQuote(
            mode="v3",
            expected_out=int(eq),
            amount_out_min=int(mq),
            v3_fee=int(fee_pick),
            quoter="v3_best_fee",
        )
    except Exception as v3_ex:
        v2_enabled = bool(getattr(cfg, "X_SIGNAL_V2_ROUTER_FALLBACK_ENABLED", True))
        if not v2_enabled:
            raise v3_ex
        try:
            v2_quote = _quote_v2_router_best(
                w3,
                token_in=token_in,
                token_out=token_out,
                amount_in=int(amount_in),
                slippage_bps=slippage_bps,
            )
        except Exception as v2_ex:
            fee_detail = "; ".join(f"fee{f}={err}" for f, err in sorted(fee_errors.items()))
            raise RuntimeError(
                f"V3 single-hop failed ({v3_ex}); V2 router failed ({v2_ex}); v3_fees=[{fee_detail}]"
            ) from v2_ex
        print(
            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL V3 quote unavailable — using V2 router path | "
            f"hops={len(v2_quote.v2_path or [])} | expected_out≈{v2_quote.expected_out}"
        )
        return v2_quote


def _log_x_signal_quote_failure(
    *,
    stage: str,
    slippage_bps: int,
    token_in: str,
    token_out: str,
    amount_in: int,
    exc: BaseException,
    fee_errors: dict[int, str] | None = None,
) -> None:
    """Structured diagnostics when V3/V2 quoting fails for X-SIGNAL fallback execution."""
    fee_detail = ""
    if fee_errors:
        fee_detail = " | v3_fee_errors=" + "; ".join(
            f"{fee}:{err[:80]}" for fee, err in sorted(fee_errors.items())
        )
    print(
        f"{_prefix}[FALLBACK ROUTER] X-SIGNAL quote failed | stage={stage} | "
        f"slip_bps={slippage_bps} | amount_in={int(amount_in)} | "
        f"token_in={_addr_probe(token_in)} | token_out={_addr_probe(token_out)} | "
        f"fees_tried=3000,500,10000 (small-first){fee_detail} | "
        f"error={type(exc).__name__}: {exc}"
    )


def _oneinch_api_key() -> str:
    return ONEINCH_API_KEY


def _log_oneinch_fallback_reason(ex: BaseException) -> None:
    if isinstance(ex, urllib.error.HTTPError):
        detail = f"HTTP {ex.code} {ex.reason}"
    elif isinstance(ex, urllib.error.URLError):
        detail = f"URL error: {ex.reason!s}"
    else:
        detail = str(ex)
    print(
        f"{_prefix}1inch unavailable ({type(ex).__name__}: {detail}) "
        "— falling back to router path quoting"
    )


def _oneinch_approve_spender() -> str:
    return oneinch_approve_spender(
        spender_endpoint=ONEINCH_SPENDER_ENDPOINT,
        api_key=_oneinch_api_key(),
    )


def _oneinch_swap_payload(
    *,
    token_in: str,
    token_out: str,
    amount_in: int,
    swap_slippage_bps: int | None = None,
) -> dict:
    # Thin compatibility wrapper: tests monkeypatch this symbol in swap_executor.
    return oneinch_swap_payload(
        swap_endpoint=ONEINCH_SWAP_ENDPOINT,
        api_key=_oneinch_api_key(),
        wallet=WALLET,
        token_in=token_in,
        token_out=token_out,
        amount_in=int(amount_in),
        default_slippage_bps=int(SWAP_SLIPPAGE_BPS),
        swap_slippage_bps=swap_slippage_bps,
    )


def _resolve_private_key(private_key_param: str | None) -> tuple[str, str]:
    """Delegate to central config resolver to keep key precedence consistent bot-wide."""
    return cfg.resolve_private_key(private_key_param, require=False)


async def approve_and_swap(
    w3,
    private_key,
    amount_in: int,
    direction: str = "USDT_TO_WMATIC",
    *,
    token_in: str | None = None,
    token_out: str | None = None,
    fallback_slippage_bps: int | None = None,
    fallback_retry_slippage_bps: int | None = None,
    fallback_min_out_extra_bps: int | None = None,
    swap_outcome: dict | None = None,
):
    print(f"{_prefix}swap EXEC | direction={direction} | amount_in={amount_in}")

    try:
        resolved_key, key_source = cfg.resolve_private_key(private_key, require=True, log_success=True)
        print(f"{_prefix}signer ready | source={key_source}")
        if token_in is None or token_out is None:
            if direction == "USDT_TO_WMATIC":
                token_in, token_out = USDT, WMATIC
            elif direction == "WMATIC_TO_USDT":
                token_in, token_out = WMATIC, USDT
            elif direction == "USDC_TO_WMATIC":
                token_in, token_out = USDC, WMATIC
            elif direction == "WMATIC_TO_USDC":
                token_in, token_out = WMATIC, USDC
            elif direction == "USDT_TO_USDC":
                token_in, token_out = USDT, USDC
            elif direction == "USDC_TO_EQUITY":
                raise ValueError("USDC_TO_EQUITY requires token_out (equity contract)")
            elif direction == "EQUITY_TO_USDC":
                raise ValueError("EQUITY_TO_USDC requires token_in (equity contract)")
            else:
                raise ValueError(f"Unsupported direction: {direction} (and no token_in/token_out provided)")

        if not token_in or not token_out:
            raise ValueError(f"Missing token address for direction {direction}. Check .env values (USDT/USDC).")

        token_in_cs = Web3.to_checksum_address(token_in)
        token_out_cs = Web3.to_checksum_address(token_out)
        if direction.startswith("USDC_TO_") and token_in_cs.lower() == Web3.to_checksum_address(USDC).lower():
            token_in_cs = _resolve_spendable_usdc_token(w3, amount_in)
        if token_in_cs.lower() == token_out_cs.lower():
            raise ValueError(
                f"{_prefix}refusing swap: token_in == token_out ({_addr_probe(str(token_in))}); check USDC/WMATIC env"
            )

        print(
            f"{_prefix}swap intent | {_addr_probe(token_in_cs)}→{_addr_probe(token_out_cs)} | "
            f"slippage_bps={SWAP_SLIPPAGE_BPS} | executor=1inch"
        )

        use_oneinch = bool(_oneinch_api_key())
        tx_payload: dict | None = None
        router = UNISWAP_V3_ROUTER
        approve_spender = router
        if use_oneinch:
            try:
                swap_payload = _oneinch_swap_payload(
                    token_in=token_in_cs,
                    token_out=token_out_cs,
                    amount_in=amount_in,
                )
                tx_payload = swap_payload["tx"]
                expected_out = int(str(swap_payload.get("dstAmount") or "0"))
                print(f"{_prefix}route | expected_out≈{expected_out} | provider=1inch")
                approve_spender = Web3.to_checksum_address(_oneinch_approve_spender())
            except Exception as ex:
                _log_oneinch_fallback_reason(ex)
                use_oneinch = False

        fb_primary = 0
        fb_retry = 0
        x_signal_preflight_quote: _FallbackQuote | None = None
        x_signal_enhanced_route = fallback_slippage_bps is not None
        if not use_oneinch:
            had_oneinch_key = bool(_oneinch_api_key())
            if not had_oneinch_key:
                print(f"{_prefix}[FALLBACK ROUTER] ONEINCH_API_KEY missing — using Uniswap V3 fallback execution.")
            else:
                print(f"{_prefix}[FALLBACK ROUTER] Using Uniswap V3 fallback execution (see 1inch message above).")
            # X-SIGNAL: defer USDC allowance until quote picks V3 vs V2 router.
            if direction.startswith("USDC_TO_") and not x_signal_enhanced_route:
                _ensure_usdc_allowance(
                    w3,
                    resolved_key,
                    amount_in,
                    router,
                    usdc_token_address=token_in_cs,
                )
            fb_primary = _fallback_router_slippage_bps()
            fb_retry = _fallback_router_retry_slippage_bps(fb_primary)
            # TEMPORARY: caller may pass relaxed fallback slippage (e.g. small high-conviction X-SIGNAL).
            if fallback_slippage_bps is not None:
                fb_primary = min(max(int(fallback_slippage_bps), _FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS), 9999)
                if fallback_retry_slippage_bps is not None:
                    fb_retry = min(
                        max(int(fallback_retry_slippage_bps), fb_primary, _FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS),
                        9999,
                    )
                else:
                    fb_retry = _fallback_router_retry_slippage_bps(fb_primary)
            elif direction == "USDC_TO_WMATIC":
                fb_primary = min(max(fb_primary, HIGH_CONVICTION_FALLBACK_PRIMARY_BPS), 9999)
                fb_retry = max(fb_retry, HIGH_CONVICTION_FALLBACK_RETRY_BPS)
                fb_retry = min(max(fb_retry, fb_primary), 9999)
            print(
                f"{_prefix}[FALLBACK ROUTER] Slippage: 1st attempt={fb_primary} bps, retry={fb_retry} bps "
                f"(base SWAP_SLIPPAGE_BPS={SWAP_SLIPPAGE_BPS})."
            )
            v3_quote_attempt1 = None
            quote_preflight_ok = False
            preflight_fee_errors: dict[int, str] = {}
            try:
                if x_signal_enhanced_route:
                    route_quote = _x_signal_quote_best_route(
                        w3,
                        token_in=token_in_cs,
                        token_out=token_out_cs,
                        amount_in=amount_in,
                        slippage_bps=fb_primary,
                        prefer_stable_fee=True,
                    )
                    if route_quote.mode == "v3":
                        print(
                            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL best V3 fee tier | fee={route_quote.v3_fee} | "
                            f"slip_bps={fb_primary} | stable_prefer_bps="
                            f"{int(getattr(cfg, 'X_SIGNAL_STABLE_FEE_PREFER_BPS', 0) or 0)}"
                        )
                    eq = route_quote.expected_out
                    mq = route_quote.amount_out_min
                    fee_pick = route_quote.v3_fee
                else:
                    fee_pick = 3000
                    eq, mq = _quote_uniswap_v3_exact_input_single(
                        w3,
                        token_in=token_in_cs,
                        token_out=token_out_cs,
                        amount_in=amount_in,
                        slippage_bps=fb_primary,
                        fee=fee_pick,
                    )
                    route_quote = _FallbackQuote(
                        mode="v3",
                        expected_out=int(eq),
                        amount_out_min=int(mq),
                        v3_fee=int(fee_pick),
                    )
                quote_preflight_ok = True
            except Exception as qex:
                if x_signal_enhanced_route:
                    _log_x_signal_quote_failure(
                        stage="pre_flight",
                        slippage_bps=fb_primary,
                        token_in=token_in_cs,
                        token_out=token_out_cs,
                        amount_in=amount_in,
                        exc=qex,
                        fee_errors=preflight_fee_errors,
                    )
                    print(
                        f"{_prefix}[FALLBACK ROUTER] X-SIGNAL pre-flight quote deferred to slippage ramp "
                        f"(will retry {fb_primary}→{fb_retry} bps)"
                    )
                else:
                    print(f"{_prefix}[FALLBACK ROUTER] Quote failed (pre-flight, {fb_primary} bps): {qex}")
                    if swap_outcome is not None:
                        swap_outcome.update(
                            success=False,
                            revert_reason=str(qex),
                            stf=False,
                            direction=direction,
                        )
                    return None
            if quote_preflight_ok:
                if fallback_min_out_extra_bps is not None and int(fallback_min_out_extra_bps) > 0:
                    mq_before = mq
                    mq = _apply_fallback_min_out_extra_buffer(mq, extra_bps=fallback_min_out_extra_bps)
                    route_quote = _FallbackQuote(
                        mode=route_quote.mode,
                        expected_out=int(eq),
                        amount_out_min=int(mq),
                        v3_fee=int(route_quote.v3_fee),
                        v2_path=route_quote.v2_path,
                        quoter=route_quote.quoter,
                    )
                    print(
                        f"{_prefix}[FALLBACK ROUTER] X-SIGNAL min_out buffer applied (signal execution quality) | "
                        f"extra_bps={int(fallback_min_out_extra_bps)} | min_out {mq_before}→{mq}"
                    )
                if x_signal_enhanced_route:
                    quote_ok, quote_detail = _x_signal_preflight_quote_sane(
                        expected_out=route_quote.expected_out,
                        amount_out_min=route_quote.amount_out_min,
                        slippage_bps=fb_primary,
                    )
                    if not quote_ok:
                        print(
                            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL pre-flight quote rejected | "
                            f"reason={quote_detail} | mode={route_quote.mode} | "
                            f"fee={route_quote.v3_fee} | deferring to slippage ramp"
                        )
                    else:
                        print(
                            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL pre-flight quote OK | mode={route_quote.mode} | "
                            f"fee={route_quote.v3_fee} | expected_out≈{route_quote.expected_out} | "
                            f"min_out={route_quote.amount_out_min} | check={quote_detail}"
                        )
                        x_signal_preflight_quote = route_quote
                else:
                    print(
                        f"{_prefix}[FALLBACK ROUTER] Pre-flight quote OK | fee={fee_pick} | "
                        f"expected_out≈{eq} | min_out={mq}"
                    )
                    v3_quote_attempt1 = (eq, mq, fee_pick, time.time())

        skip_generic_approve = x_signal_enhanced_route and not use_oneinch
        if not skip_generic_approve:
            approve_contract = w3.eth.contract(address=token_in_cs, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},{"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"}])
            approve_spender_cs = Web3.to_checksum_address(approve_spender)
            current_allowance = int(approve_contract.functions.allowance(WALLET, approve_spender_cs).call())
            if current_allowance < int(amount_in):
                nonce = w3.eth.get_transaction_count(WALLET)
                approve_tx = approve_contract.functions.approve(approve_spender_cs, amount_in).build_transaction({
                    "from": WALLET,
                    "nonce": nonce,
                    "gas": 140000,
                    "gasPrice": w3.eth.gas_price * 15 // 10,
                    "chainId": 137,
                })
                signed_approve = w3.eth.account.sign_transaction(approve_tx, resolved_key)
                approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
                print(f"✅ Approve Tx: {approve_hash.hex()}")
                receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=300)
                if receipt["status"] == 0:
                    print("❌ Approve failed!")
                    return None
                # Some ERC20s can report approve tx success while leaving allowance unchanged; verify before swap.
                updated_allowance = int(approve_contract.functions.allowance(WALLET, approve_spender_cs).call())
                if updated_allowance < int(amount_in):
                    print(
                        f"{_prefix}❌ Allowance still insufficient after approve | "
                        f"spender={approve_spender_cs} | current={updated_allowance} | needed={int(amount_in)}"
                    )
                    return None
                print("✅ Approve confirmed!")
                await asyncio.sleep(5)
            else:
                print(
                    f"{_prefix}Allowance sufficient before approve | spender={approve_spender_cs} | "
                    f"current={current_allowance} | needed={int(amount_in)} | action=skip_approve"
                )

        if use_oneinch and tx_payload is not None:
            oneinch_slip_bps = SWAP_SLIPPAGE_BPS
            for swap_pass in (0, 1):
                if swap_pass > 0:
                    oneinch_slip_bps = min(SWAP_SLIPPAGE_BPS + ONCHAIN_SWAP_RETRY_EXTRA_BPS, 9999)
                    print(
                        f"{_prefix}RETRY ATTEMPT 1/1 | Increasing slippage to {oneinch_slip_bps} bps "
                        "(1inch quote refresh)"
                    )
                    try:
                        swap_payload = _oneinch_swap_payload(
                            token_in=token_in_cs,
                            token_out=token_out_cs,
                            amount_in=amount_in,
                            swap_slippage_bps=oneinch_slip_bps,
                        )
                        tx_payload = swap_payload["tx"]
                    except Exception as rex:
                        print(f"{_prefix}❌ 1inch retry quote failed: {rex}")
                        return None

                nonce_swap = w3.eth.get_transaction_count(WALLET)
                _gp = tx_payload.get("gasPrice")
                gas_price = int(w3.eth.gas_price * 15 // 10) if _gp is None else int(_gp)
                _gl = tx_payload.get("gas")
                gas_limit = 450000 if _gl is None else int(_gl)
                swap_tx = {
                    "from": WALLET,
                    "nonce": nonce_swap,
                    "to": Web3.to_checksum_address(str(tx_payload["to"])),
                    "data": str(tx_payload["data"]),
                    "value": int(tx_payload.get("value") or 0),
                    "gas": gas_limit,
                    "gasPrice": gas_price,
                    "chainId": 137,
                }
                signed_swap = w3.eth.account.sign_transaction(swap_tx, resolved_key)
                swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
                print(f"✅ REAL TX HASH: {swap_hash.hex()}")
                print(f"https://polygonscan.com/tx/{swap_hash.hex()}")

                receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=300)
                if receipt["status"] == 1:
                    print("✅ Swap confirmed!")
                    return swap_hash.hex()

                print(f"{_prefix}❌ Swap failed on-chain (1inch path, pass {swap_pass + 1}/2).")
                if swap_pass == 0:
                    continue
                return None

        v3_quote_attempt1: tuple | None = None
        # CRITICAL: X-SIGNAL rotation only pays off when selected BUYs actually fill on-chain.
        if x_signal_enhanced_route:
            ramp_bps = _x_signal_fallback_slippage_ramp(fb_primary, fb_retry)
            slip_attempts = list(enumerate(ramp_bps))
            print(
                f"{_prefix}[FALLBACK ROUTER] X-SIGNAL slippage ramp | "
                f"steps={len(ramp_bps)} | bps={' → '.join(str(b) for b in ramp_bps)}"
            )
        else:
            slip_attempts = [(0, fb_primary), (1, fb_retry)]
        for attempt_idx, slip_bps in slip_attempts:
            route_quote: _FallbackQuote | None = None
            quote_ts: float | None = None
            quote_age_s: float | None = None
            if attempt_idx == 0 and x_signal_enhanced_route and x_signal_preflight_quote is not None:
                route_quote = x_signal_preflight_quote
                quote_ts = time.time()
            elif attempt_idx == 0 and v3_quote_attempt1 is not None:
                if len(v3_quote_attempt1) >= 4:
                    expected_out, amount_out_min, v3_fee, quote_ts = v3_quote_attempt1[:4]
                else:
                    expected_out, amount_out_min, v3_fee = v3_quote_attempt1[:3]
                    quote_ts = None
                route_quote = _FallbackQuote(
                    mode="v3",
                    expected_out=int(expected_out),
                    amount_out_min=int(amount_out_min),
                    v3_fee=int(v3_fee),
                )
            else:
                if attempt_idx > 0 and x_signal_enhanced_route:
                    requote_delay = float(
                        getattr(cfg, "X_SIGNAL_FALLBACK_REQUOTE_DELAY_SECONDS", 0.0) or 0.0
                    )
                    if requote_delay > 0:
                        print(
                            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL re-quote delay | "
                            f"wait={requote_delay:.1f}s | attempt={attempt_idx + 1}/{len(slip_attempts)}"
                        )
                        await asyncio.sleep(requote_delay)
                ramp_fee_errors: dict[int, str] = {}
                try:
                    if x_signal_enhanced_route:
                        route_quote = _x_signal_quote_best_route(
                            w3,
                            token_in=token_in_cs,
                            token_out=token_out_cs,
                            amount_in=amount_in,
                            slippage_bps=slip_bps,
                            prefer_stable_fee=True,
                        )
                    else:
                        expected_out, amount_out_min = _quote_uniswap_v3_exact_input_single(
                            w3,
                            token_in=token_in_cs,
                            token_out=token_out_cs,
                            amount_in=amount_in,
                            slippage_bps=slip_bps,
                            fee=3000,
                        )
                        route_quote = _FallbackQuote(
                            mode="v3",
                            expected_out=int(expected_out),
                            amount_out_min=int(amount_out_min),
                            v3_fee=3000,
                        )
                except Exception as qex:
                    if x_signal_enhanced_route:
                        _log_x_signal_quote_failure(
                            stage=f"ramp_{attempt_idx + 1}",
                            slippage_bps=slip_bps,
                            token_in=token_in_cs,
                            token_out=token_out_cs,
                            amount_in=amount_in,
                            exc=qex,
                            fee_errors=ramp_fee_errors,
                        )
                    else:
                        print(
                            f"{_prefix}[FALLBACK ROUTER] Quote failed (attempt {attempt_idx + 1}/"
                            f"{len(slip_attempts)}, {slip_bps} bps): {qex}"
                        )
                    if swap_outcome is not None:
                        swap_outcome.update(
                            success=False,
                            revert_reason=str(qex),
                            stf=False,
                            direction=direction,
                            slippage_bps=slip_bps,
                        )
                    if attempt_idx < len(slip_attempts) - 1:
                        next_bps = slip_attempts[attempt_idx + 1][1]
                        print(
                            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL quote retry | "
                            f"next_slip_bps={next_bps} (was {slip_bps})"
                        )
                        continue
                    print(f"{_prefix}❌ X-SIGNAL quote failed after all slippage ramp steps.")
                    return None
                if (
                    x_signal_enhanced_route
                    and fallback_min_out_extra_bps is not None
                    and int(fallback_min_out_extra_bps) > 0
                    and route_quote is not None
                ):
                    mq_before = route_quote.amount_out_min
                    route_quote = _FallbackQuote(
                        mode=route_quote.mode,
                        expected_out=route_quote.expected_out,
                        amount_out_min=_apply_fallback_min_out_extra_buffer(
                            route_quote.amount_out_min,
                            extra_bps=fallback_min_out_extra_bps,
                        ),
                        v3_fee=route_quote.v3_fee,
                        v2_path=route_quote.v2_path,
                        quoter=route_quote.quoter,
                    )
                    print(
                        f"{_prefix}[FALLBACK ROUTER] X-SIGNAL min_out buffer applied (signal execution quality) | "
                        f"extra_bps={int(fallback_min_out_extra_bps)} | min_out {mq_before}→{route_quote.amount_out_min}"
                    )
                quote_ts = time.time()

            if route_quote is None:
                print(f"{_prefix}❌ Missing route quote after ramp step {attempt_idx + 1}.")
                return None
            expected_out = route_quote.expected_out
            amount_out_min = route_quote.amount_out_min
            v3_fee = route_quote.v3_fee
            route_mode = route_quote.mode
            v2_path = route_quote.v2_path

            if x_signal_enhanced_route:
                quote_age_s = _x_signal_quote_age_seconds(quote_ts)
                if _x_signal_quote_stale(quote_ts):
                    print(
                        f"{_prefix}[FALLBACK ROUTER] X-SIGNAL pre-flight stale quote | "
                        f"age_s={quote_age_s:.1f} | max_age_s={_x_signal_preflight_max_quote_age_seconds():.1f} | "
                        f"re-quoting before submit"
                    )
                    try:
                        route_quote = _x_signal_quote_best_route(
                            w3,
                            token_in=token_in_cs,
                            token_out=token_out_cs,
                            amount_in=amount_in,
                            slippage_bps=slip_bps,
                            prefer_stable_fee=True,
                        )
                        if fallback_min_out_extra_bps is not None and int(fallback_min_out_extra_bps) > 0:
                            route_quote = _FallbackQuote(
                                mode=route_quote.mode,
                                expected_out=route_quote.expected_out,
                                amount_out_min=_apply_fallback_min_out_extra_buffer(
                                    route_quote.amount_out_min,
                                    extra_bps=fallback_min_out_extra_bps,
                                ),
                                v3_fee=route_quote.v3_fee,
                                v2_path=route_quote.v2_path,
                                quoter=route_quote.quoter,
                            )
                        expected_out = route_quote.expected_out
                        amount_out_min = route_quote.amount_out_min
                        v3_fee = route_quote.v3_fee
                        route_mode = route_quote.mode
                        v2_path = route_quote.v2_path
                        quote_ts = time.time()
                        quote_age_s = _x_signal_quote_age_seconds(quote_ts)
                    except Exception as qex:
                        print(
                            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL stale re-quote failed | "
                            f"attempt={attempt_idx + 1} | {qex}"
                        )
                        if swap_outcome is not None:
                            swap_outcome.update(
                                success=False,
                                revert_reason=str(qex),
                                stf=False,
                                direction=direction,
                            )
                        if attempt_idx < len(slip_attempts) - 1:
                            continue
                        return None
                quote_ok, quote_detail = _x_signal_preflight_quote_sane(
                    expected_out=expected_out,
                    amount_out_min=amount_out_min,
                    slippage_bps=slip_bps,
                )
                if not quote_ok:
                    print(
                        f"{_prefix}[FALLBACK ROUTER] X-SIGNAL pre-flight quote rejected | "
                        f"attempt={attempt_idx + 1} | reason={quote_detail}"
                    )
                    if attempt_idx < len(slip_attempts) - 1:
                        next_bps = slip_attempts[attempt_idx + 1][1]
                        print(
                            f"{_prefix}[FALLBACK ROUTER] X-SIGNAL sanity retry | "
                            f"next_slip_bps={next_bps} (was {slip_bps})"
                        )
                        continue
                    if swap_outcome is not None:
                        swap_outcome.update(
                            success=False,
                            revert_reason=f"preflight_quote:{quote_detail}",
                            stf=False,
                            direction=direction,
                            slippage_bps=slip_bps,
                        )
                    return None

            route_label = (
                f"v2_path_hops={len(v2_path or [])}"
                if route_mode == "v2"
                else f"fee={v3_fee}"
            )
            print(
                f"{_prefix}[FALLBACK ROUTER] route attempt={attempt_idx + 1}/{len(slip_attempts)} | "
                f"mode={route_mode} | {route_label} | slip_bps={slip_bps} | expected_out≈{expected_out} | "
                f"min_out={amount_out_min}"
                + (
                    f" | quote_age_s={quote_age_s:.1f}"
                    if x_signal_enhanced_route and quote_age_s is not None
                    else ""
                )
            )

            swap_router = ROUTER if route_mode == "v2" else router
            if direction.startswith("USDC_TO_"):
                _ensure_usdc_allowance(
                    w3,
                    resolved_key,
                    amount_in,
                    swap_router,
                    usdc_token_address=token_in_cs,
                )

            nonce_swap = w3.eth.get_transaction_count(WALLET)
            router_cs = Web3.to_checksum_address(swap_router)
            deadline = int(time.time()) + 300
            if route_mode == "v2":
                if not v2_path:
                    print(f"{_prefix}❌ V2 route missing path at attempt {attempt_idx + 1}.")
                    return None
                path_cs = [Web3.to_checksum_address(a) for a in v2_path]
                swap_contract = w3.eth.contract(address=router_cs, abi=ROUTER_SWAP_AND_QUOTE_ABI)
                gas_limit = 650000 if len(path_cs) > 2 else 520000
                swap_tx = swap_contract.functions.swapExactTokensForTokens(
                    int(amount_in),
                    int(amount_out_min),
                    path_cs,
                    WALLET,
                    deadline,
                ).build_transaction({
                    "from": WALLET,
                    "nonce": nonce_swap,
                    "gas": gas_limit,
                    "gasPrice": w3.eth.gas_price * 15 // 10,
                    "chainId": 137,
                })
            else:
                swap_contract = w3.eth.contract(address=router_cs, abi=UNISWAP_V3_ROUTER_ABI)
                gas_limit = 520000
                v3_params = (
                    Web3.to_checksum_address(token_in_cs),
                    Web3.to_checksum_address(token_out_cs),
                    int(v3_fee),
                    WALLET,
                    deadline,
                    int(amount_in),
                    int(amount_out_min),
                    0,
                )
                swap_tx = swap_contract.functions.exactInputSingle(v3_params).build_transaction({
                    "from": WALLET,
                    "nonce": nonce_swap,
                    "gas": gas_limit,
                    "gasPrice": w3.eth.gas_price * 15 // 10,
                    "chainId": 137,
                })

            tx_for_call = {
                "from": WALLET,
                "to": router_cs,
                "data": swap_tx.get("data"),
                "value": swap_tx.get("value", 0),
            }
            if x_signal_enhanced_route:
                gas_ok, gas_detail = _x_signal_preflight_gas_sane(
                    w3,
                    {
                        "from": WALLET,
                        "to": router_cs,
                        "data": swap_tx.get("data"),
                        "value": int(swap_tx.get("value") or 0),
                    },
                )
                print(
                    f"{_prefix}[FALLBACK ROUTER] X-SIGNAL pre-flight gas | "
                    f"attempt={attempt_idx + 1} | {gas_detail}"
                )
                if not gas_ok:
                    if swap_outcome is not None:
                        swap_outcome.update(
                            success=False,
                            revert_reason=f"preflight_gas:{gas_detail}",
                            stf=False,
                            direction=direction,
                            slippage_bps=slip_bps,
                            amount_out_min=amount_out_min,
                            expected_out=expected_out,
                            fee_tier=f"v2_hops={len(v2_path or [])}" if route_mode == "v2" else v3_fee,
                            min_out_extra_bps=fallback_min_out_extra_bps,
                        )
                    if attempt_idx < len(slip_attempts) - 1:
                        next_bps = slip_attempts[attempt_idx + 1][1]
                        print(
                            f"{_prefix}RETRY ATTEMPT {attempt_idx + 1}/{len(slip_attempts) - 1} | "
                            f"pre-flight gas failed — trying slippage {next_bps} bps (was {slip_bps})"
                        )
                        continue
                    print(f"{_prefix}❌ X-SIGNAL pre-flight gas check failed after all ramp steps.")
                    return None
            receipt = None
            try:
                signed_swap = w3.eth.account.sign_transaction(swap_tx, resolved_key)
                swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
                print(f"✅ REAL TX HASH: {swap_hash.hex()}")
                print(f"https://polygonscan.com/tx/{swap_hash.hex()}")
                receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=300)
            except Exception as tx_ex:  # noqa: BLE001
                revert_reason = _try_get_revert_reason(w3, tx_for_call=tx_for_call)
                stf = _is_stf_revert_reason(revert_reason)
                print(
                    f"{_prefix}[FALLBACK ROUTER] Swap submission/wait failed "
                    f"(attempt {attempt_idx + 1}/{len(slip_attempts)}): {tx_ex} | "
                    f"slip_bps={slip_bps} | min_out={amount_out_min} | stf={stf} | revert={revert_reason}"
                )
                if swap_outcome is not None:
                    swap_outcome.update(
                        success=False,
                        revert_reason=revert_reason,
                        stf=stf,
                        direction=direction,
                        fee_tier=f"v2_hops={len(v2_path or [])}" if route_mode == "v2" else v3_fee,
                        slippage_bps=slip_bps,
                        amount_out_min=amount_out_min,
                        expected_out=expected_out,
                        min_out_extra_bps=fallback_min_out_extra_bps,
                    )
                if attempt_idx < len(slip_attempts) - 1:
                    next_bps = slip_attempts[attempt_idx + 1][1]
                    print(
                        f"{_prefix}RETRY ATTEMPT {attempt_idx + 1}/{len(slip_attempts) - 1} | "
                        f"Increasing slippage to {next_bps} bps (router fallback; was {slip_bps} bps)"
                    )
                    continue
                print(f"{_prefix}❌ Swap failed on-chain after fallback retries.")
                return None
            if receipt is None:
                print(f"{_prefix}[FALLBACK ROUTER] Missing receipt after swap attempt; aborting.")
                return None
            if receipt["status"] == 1:
                print(f"{_prefix}✅ Swap confirmed ([FALLBACK ROUTER] attempt {attempt_idx + 1}).")
                if swap_outcome is not None:
                    swap_outcome.update(
                        success=True,
                        stf=False,
                        direction=direction,
                        fee_tier=f"v2_hops={len(v2_path or [])}" if route_mode == "v2" else v3_fee,
                    )
                return swap_hash.hex()

            revert_reason = _try_get_revert_reason(w3, tx_for_call=tx_for_call)
            stf = _is_stf_revert_reason(revert_reason)
            print(
                f"{_prefix}[FALLBACK ROUTER] On-chain swap reverted (attempt {attempt_idx + 1}). "
                f"Tx: {swap_hash.hex()} | slip_bps={slip_bps} | min_out={amount_out_min} | "
                f"fee={v3_fee} | stf={stf} | revert={revert_reason}"
            )
            if swap_outcome is not None:
                swap_outcome.update(
                    success=False,
                    revert_reason=revert_reason,
                    stf=stf,
                    direction=direction,
                    fee_tier=f"v2_hops={len(v2_path or [])}" if route_mode == "v2" else v3_fee,
                    slippage_bps=slip_bps,
                    tx_hash=swap_hash.hex(),
                    amount_out_min=amount_out_min,
                    expected_out=expected_out,
                    min_out_extra_bps=fallback_min_out_extra_bps,
                )
            if attempt_idx < len(slip_attempts) - 1:
                next_bps = slip_attempts[attempt_idx + 1][1]
                print(
                    f"{_prefix}RETRY ATTEMPT {attempt_idx + 1}/{len(slip_attempts) - 1} | "
                    f"Increasing slippage to {next_bps} bps (router fallback; was {slip_bps} bps)"
                )
                continue
            print(f"{_prefix}❌ Swap failed on-chain after fallback retries.")
            return None

    except Exception as e:
        print(f"❌ Error in approve_and_swap: {e}")
        import traceback

        traceback.print_exc()
        return None
