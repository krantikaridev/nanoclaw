import json
import os
import asyncio
import time
import urllib.error
import urllib.parse
import urllib.request

from web3 import Web3
from dotenv import load_dotenv

from constants import (
    ERC20_ABI,
    LOG_PREFIX,
    ROUTER,
    ROUTER_SWAP_AND_QUOTE_ABI,
    USDC,
    WALLET,
    USDT,
    WMATIC,
)

load_dotenv()

SWAP_SLIPPAGE_BPS = int(os.getenv("SWAP_SLIPPAGE_BPS", "100"))
# When 1inch is skipped or fails, router quoting uses higher slippage than SWAP_SLIPPAGE_BPS.
# Optional overrides; otherwise derived from base slippage (see ``_fallback_router_slippage_bps``).
FALLBACK_ROUTER_SLIPPAGE_BPS_RAW = os.getenv("FALLBACK_ROUTER_SLIPPAGE_BPS", "").strip()
FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS_RAW = os.getenv("FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS", "").strip()
# +0.5% default: one on-chain retry bumps slippage by this many bps (1inch + router fallback).
ONCHAIN_SWAP_RETRY_EXTRA_BPS = int(os.getenv("ONCHAIN_SWAP_RETRY_EXTRA_BPS", "50"))
ONEINCH_SWAP_ENDPOINT = os.getenv("ONEINCH_SWAP_ENDPOINT", "https://api.1inch.dev/swap/v5.2/137/swap")
ONEINCH_SPENDER_ENDPOINT = os.getenv(
    "ONEINCH_SPENDER_ENDPOINT",
    "https://api.1inch.dev/swap/v5.2/137/approve/spender",
)

_prefix = LOG_PREFIX + " " if LOG_PREFIX else ""


_FALLBACK_ROUTER_SLIPPAGE_FLOOR_BPS = 600
_QUICKSWAP_V2_ROUTER = Web3.to_checksum_address("0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")


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


def _addr_probe(addr: str) -> str:
    cs = Web3.to_checksum_address(addr)
    return f"{cs[:10]}…{cs[-6:]}"


def _ensure_usdc_allowance(w3, resolved_key: str, amount_in: int, router_address: str) -> None:
    router_cs = Web3.to_checksum_address(router_address)
    usdc_cs = Web3.to_checksum_address(USDC)
    current_allowance = int(
        w3.eth.contract(address=usdc_cs, abi=ERC20_ABI).functions.allowance(WALLET, router_cs).call()
    )
    if current_allowance >= int(amount_in):
        print(
            f"{_prefix}Allowance check | router={router_cs} | current={current_allowance} | "
            f"needed={int(amount_in)} | action=none"
        )
        return

    approve_tx = w3.eth.contract(address=usdc_cs, abi=ERC20_ABI).functions.approve(
        router_cs, 2**256 - 1
    ).build_transaction({
        "from": WALLET,
        "nonce": w3.eth.get_transaction_count(WALLET),
        "gas": 140000,
        "gasPrice": w3.eth.gas_price * 15 // 10,
        "chainId": 137,
    })
    signed_approve = w3.eth.account.sign_transaction(approve_tx, resolved_key)
    approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=300)
    if receipt["status"] == 0:
        raise RuntimeError(f"{_prefix}USDC max approval failed for router {router_cs}")
    print(
        f"{_prefix}Allowance check | router={router_cs} | current={current_allowance} | "
        f"needed={int(amount_in)} | action=approved/max"
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

    min_out = max(1, (best_amt * (6000 - min(slip, 9999))) // 6000)
    return best_path, best_amt, min_out


def _oneinch_api_key() -> str:
    return (os.getenv("ONEINCH_API_KEY") or os.getenv("INCH_API_KEY") or "").strip()


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


def _oneinch_headers() -> dict[str, str]:
    api_key = _oneinch_api_key()
    if not api_key:
        raise ValueError("Missing ONEINCH_API_KEY (required for 1inch swap API)")
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _oneinch_get_json(url: str) -> dict:
    req = urllib.request.Request(url=url, headers=_oneinch_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310
        payload = response.read().decode("utf-8")
    data = json.loads(payload or "{}")
    if not isinstance(data, dict):
        raise ValueError("Invalid 1inch response format")
    return data


def _oneinch_approve_spender() -> str:
    data = _oneinch_get_json(ONEINCH_SPENDER_ENDPOINT)
    spender = str(data.get("address", "")).strip()
    if not spender:
        raise ValueError("1inch approve/spender response missing address")
    return spender


def _oneinch_swap_payload(
    *,
    token_in: str,
    token_out: str,
    amount_in: int,
    swap_slippage_bps: int | None = None,
) -> dict:
    bps = SWAP_SLIPPAGE_BPS if swap_slippage_bps is None else int(swap_slippage_bps)
    slippage_percent = max(0.1, float(bps) / 100.0)
    params = {
        "src": token_in,
        "dst": token_out,
        "amount": str(int(amount_in)),
        "from": WALLET,
        "origin": WALLET,
        "receiver": WALLET,
        "slippage": f"{slippage_percent:.2f}",
        "disableEstimate": "false",
        "allowPartialFill": "false",
    }
    # Using 1inch for better execution (Tier 1 - 2026-05-01)
    query = urllib.parse.urlencode(params)
    url = f"{ONEINCH_SWAP_ENDPOINT}?{query}"
    data = _oneinch_get_json(url)
    tx_data = data.get("tx")
    if not isinstance(tx_data, dict) or not tx_data.get("to") or not tx_data.get("data"):
        raise ValueError("1inch swap response missing tx payload")
    return data


async def approve_and_swap(
    w3,
    private_key,
    amount_in: int,
    direction: str = "USDT_TO_WMATIC",
    *,
    token_in: str | None = None,
    token_out: str | None = None,
):
    print(f"{_prefix}swap EXEC | direction={direction} | amount_in={amount_in}")

    try:
        resolved_key = private_key or os.getenv("POLYGON_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
        if not resolved_key:
            raise ValueError("Missing private key (set POLYGON_PRIVATE_KEY)")
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
        router = _QUICKSWAP_V2_ROUTER
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

        path_candidates: list[list[str]] | None = None
        fb_primary = 0
        fb_retry = 0
        router_quote_attempt1: tuple[list[str], int, int] | None = None
        if not use_oneinch:
            had_oneinch_key = bool(_oneinch_api_key())
            if not had_oneinch_key:
                print(f"{_prefix}[FALLBACK ROUTER] ONEINCH_API_KEY missing — using on-chain router execution.")
            else:
                print(f"{_prefix}[FALLBACK ROUTER] Using on-chain router execution (see 1inch message above).")
            if token_in_cs.lower() == Web3.to_checksum_address(USDC).lower():
                _ensure_usdc_allowance(w3, resolved_key, amount_in, router)
            path_candidates = build_polygon_swap_path_candidates(token_in_cs, token_out_cs)
            fb_primary = _fallback_router_slippage_bps()
            fb_retry = _fallback_router_retry_slippage_bps(fb_primary)
            print(
                f"{_prefix}[FALLBACK ROUTER] Slippage: 1st attempt={fb_primary} bps, retry={fb_retry} bps "
                f"(base SWAP_SLIPPAGE_BPS={SWAP_SLIPPAGE_BPS})."
            )
            try:
                router_quote_attempt1 = _best_quote_path(
                    w3,
                    router=router,
                    amount_in=amount_in,
                    paths=path_candidates,
                    slippage_bps=fb_primary,
                )
            except Exception as qex:
                print(f"{_prefix}[FALLBACK ROUTER] Quote failed (pre-flight, {fb_primary} bps): {qex}")
                return None
            cq, eq, mq = router_quote_attempt1
            print(
                f"{_prefix}[FALLBACK ROUTER] Pre-flight quote OK | hops={len(cq) - 1} | "
                f"expected_out≈{eq} | min_out={mq}"
            )

        nonce = w3.eth.get_transaction_count(WALLET)
        approve_contract = w3.eth.contract(address=token_in_cs, abi=ERC20_ABI)
        approve_tx = approve_contract.functions.approve(approve_spender, amount_in).build_transaction({
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
        print("✅ Approve confirmed!")
        await asyncio.sleep(5)

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

        slip_attempts: list[tuple[int, int]] = [(0, fb_primary), (1, fb_retry)]
        for attempt_idx, slip_bps in slip_attempts:
            if attempt_idx == 0 and router_quote_attempt1 is not None:
                chosen_path, expected_out, amount_out_min = router_quote_attempt1
            else:
                assert path_candidates is not None
                try:
                    chosen_path, expected_out, amount_out_min = _best_quote_path(
                        w3,
                        router=router,
                        amount_in=amount_in,
                        paths=path_candidates,
                        slippage_bps=slip_bps,
                    )
                except Exception as qex:
                    print(
                        f"{_prefix}[FALLBACK ROUTER] Quote failed (attempt {attempt_idx + 1}/{len(slip_attempts)}, "
                        f"{slip_bps} bps): {qex}"
                    )
                    return None

            print(
                f"{_prefix}[FALLBACK ROUTER] route attempt={attempt_idx + 1}/{len(slip_attempts)} | "
                f"hops={len(chosen_path) - 1} | slip_bps={slip_bps} | expected_out≈{expected_out} | "
                f"min_out={amount_out_min}"
            )

            nonce_swap = w3.eth.get_transaction_count(WALLET)
            swap_contract = w3.eth.contract(address=router, abi=ROUTER_SWAP_AND_QUOTE_ABI)
            gas_limit = 320000 if len(chosen_path) <= 2 else 520000
            swap_tx = swap_contract.functions.swapExactTokensForTokens(
                amount_in,
                amount_out_min,
                chosen_path,
                WALLET,
                int(time.time()) + 300,
            ).build_transaction({
                "from": WALLET,
                "nonce": nonce_swap,
                "gas": gas_limit,
                "gasPrice": w3.eth.gas_price * 15 // 10,
                "chainId": 137,
            })

            signed_swap = w3.eth.account.sign_transaction(swap_tx, resolved_key)
            swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
            print(f"✅ REAL TX HASH: {swap_hash.hex()}")
            print(f"https://polygonscan.com/tx/{swap_hash.hex()}")

            receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=300)
            if receipt["status"] == 1:
                print(f"{_prefix}✅ Swap confirmed ([FALLBACK ROUTER] attempt {attempt_idx + 1}).")
                return swap_hash.hex()

            print(
                f"{_prefix}[FALLBACK ROUTER] On-chain swap reverted (attempt {attempt_idx + 1}). "
                f"Tx: {swap_hash.hex()}"
            )
            if attempt_idx == 0:
                print(
                    f"{_prefix}RETRY ATTEMPT 1/1 | Increasing slippage to {fb_retry} bps "
                    f"(router fallback; was {fb_primary} bps)"
                )
                continue
            print(f"{_prefix}❌ Swap failed on-chain after fallback retry.")
            return None

    except Exception as e:
        print(f"❌ Error in approve_and_swap: {e}")
        import traceback

        traceback.print_exc()
        return None
