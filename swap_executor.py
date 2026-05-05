import asyncio
import time
import urllib.error

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

def _force_max_approval(w3, private_key, router_address, token_address="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"):
    """One-time startup MAX approval helper for stubborn Polygon RPC lag."""
    from web3 import Web3
    import time
    account = w3.eth.account.from_key(private_key)
    wallet = account.address
    token = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=[
            {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
            {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
        ]
    )
    MAX = (1 << 256) - 1
    print(f"[FORCE-MAX-APPROVE] Forcing fresh MAX approval for router {router_address}")
    tx = token.functions.approve(router_address, MAX).build_transaction({
        "from": wallet,
        "nonce": w3.eth.get_transaction_count(wallet),
        "gas": 80000,
        "gasPrice": int(w3.eth.gas_price * 2.2),
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"[FORCE-MAX-APPROVE] Sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status == 1:
        time.sleep(8)  # ← Increased to 8 seconds for maximum propagation safety
        print("[FORCE-MAX-APPROVE] ✅ Fresh MAX confirmed + fully propagated (ready for swap)")
    else:
        print("[FORCE-MAX-APPROVE] ❌ Approval tx failed")

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
    """Resolve signer key precedence: POLYGON_PRIVATE_KEY -> PRIVATE_KEY -> function arg."""
    env_polygon_key = cfg.env_str("POLYGON_PRIVATE_KEY", "")
    env_legacy_key = cfg.env_str("PRIVATE_KEY", "")
    resolved_key = env_polygon_key or env_legacy_key or (private_key_param or "")
    key_source = (
        "POLYGON_PRIVATE_KEY"
        if env_polygon_key
        else ("PRIVATE_KEY" if env_legacy_key else ("function_arg" if private_key_param else "missing"))
    )
    return resolved_key, key_source


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
        resolved_key, key_source = _resolve_private_key(private_key)
        if not resolved_key:
            raise ValueError("Missing private key (set POLYGON_PRIVATE_KEY or PRIVATE_KEY, or pass private_key)")
        print(f"{_prefix}private key resolved | source={key_source}")
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
        v3_quote_attempt1: tuple[int, int] | None = None
        if not use_oneinch:
            had_oneinch_key = bool(_oneinch_api_key())
            if not had_oneinch_key:
                print(f"{_prefix}[FALLBACK ROUTER] ONEINCH_API_KEY missing — using Uniswap V3 fallback execution.")
            else:
                print(f"{_prefix}[FALLBACK ROUTER] Using Uniswap V3 fallback execution (see 1inch message above).")
            if direction.startswith("USDC_TO_"):
                _ensure_usdc_allowance(
                    w3,
                    resolved_key,
                    amount_in,
                    router,
                    usdc_token_address=token_in_cs,
                )
            fb_primary = _fallback_router_slippage_bps()
            fb_retry = _fallback_router_retry_slippage_bps(fb_primary)
            if direction == "USDC_TO_WMATIC":
                fb_primary = min(max(fb_primary, HIGH_CONVICTION_FALLBACK_PRIMARY_BPS), 9999)
                fb_retry = max(fb_retry, HIGH_CONVICTION_FALLBACK_RETRY_BPS)
                fb_retry = min(max(fb_retry, fb_primary), 9999)
            print(
                f"{_prefix}[FALLBACK ROUTER] Slippage: 1st attempt={fb_primary} bps, retry={fb_retry} bps "
                f"(base SWAP_SLIPPAGE_BPS={SWAP_SLIPPAGE_BPS})."
            )
            try:
                v3_quote_attempt1 = _quote_uniswap_v3_exact_input_single(
                    w3,
                    token_in=token_in_cs,
                    token_out=token_out_cs,
                    amount_in=amount_in,
                    slippage_bps=fb_primary,
                    fee=3000,
                )
            except Exception as qex:
                print(f"{_prefix}[FALLBACK ROUTER] Quote failed (pre-flight, {fb_primary} bps): {qex}")
                return None
            eq, mq = v3_quote_attempt1
            print(
                f"{_prefix}[FALLBACK ROUTER] Pre-flight quote OK | fee=3000 | "
                f"expected_out≈{eq} | min_out={mq}"
            )

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

        slip_attempts: list[tuple[int, int]] = [(0, fb_primary), (1, fb_retry)]
        for attempt_idx, slip_bps in slip_attempts:
            if attempt_idx == 0 and v3_quote_attempt1 is not None:
                expected_out, amount_out_min = v3_quote_attempt1
            else:
                try:
                    expected_out, amount_out_min = _quote_uniswap_v3_exact_input_single(
                        w3,
                        token_in=token_in_cs,
                        token_out=token_out_cs,
                        amount_in=amount_in,
                        slippage_bps=slip_bps,
                        fee=3000,
                    )
                except Exception as qex:
                    print(
                        f"{_prefix}[FALLBACK ROUTER] Quote failed (attempt {attempt_idx + 1}/{len(slip_attempts)}, "
                        f"{slip_bps} bps): {qex}"
                    )
                    return None
            print(
                f"{_prefix}[FALLBACK ROUTER] route attempt={attempt_idx + 1}/{len(slip_attempts)} | "
                f"fee=3000 | slip_bps={slip_bps} | expected_out≈{expected_out} | "
                f"min_out={amount_out_min}"
            )

            nonce_swap = w3.eth.get_transaction_count(WALLET)
            router_cs = Web3.to_checksum_address(router)
            swap_contract = w3.eth.contract(address=router_cs, abi=UNISWAP_V3_ROUTER_ABI)
            gas_limit = 520000
            v3_params = (
                Web3.to_checksum_address(token_in_cs),
                Web3.to_checksum_address(token_out_cs),
                3000,
                WALLET,
                int(time.time()) + 300,
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
            receipt = None
            try:
                signed_swap = w3.eth.account.sign_transaction(swap_tx, resolved_key)
                swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
                print(f"✅ REAL TX HASH: {swap_hash.hex()}")
                print(f"https://polygonscan.com/tx/{swap_hash.hex()}")
                receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=300)
            except Exception as tx_ex:  # noqa: BLE001
                revert_reason = _try_get_revert_reason(w3, tx_for_call=tx_for_call)
                print(
                    f"{_prefix}[FALLBACK ROUTER] Swap submission/wait failed "
                    f"(attempt {attempt_idx + 1}/{len(slip_attempts)}): {tx_ex} | revert={revert_reason}"
                )
                if attempt_idx == 0:
                    print(
                        f"{_prefix}RETRY ATTEMPT 1/1 | Increasing slippage to {fb_retry} bps "
                        f"(router fallback; was {fb_primary} bps)"
                    )
                    continue
                print(f"{_prefix}❌ Swap failed on-chain after fallback retry.")
                return None
            if receipt is None:
                print(f"{_prefix}[FALLBACK ROUTER] Missing receipt after swap attempt; aborting.")
                return None
            if receipt["status"] == 1:
                print(f"{_prefix}✅ Swap confirmed ([FALLBACK ROUTER] attempt {attempt_idx + 1}).")
                return swap_hash.hex()

            revert_reason = _try_get_revert_reason(w3, tx_for_call=tx_for_call)
            print(
                f"{_prefix}[FALLBACK ROUTER] On-chain swap reverted (attempt {attempt_idx + 1}). "
                f"Tx: {swap_hash.hex()} | receipt={dict(receipt)} | revert={revert_reason}"
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
