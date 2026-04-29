import os
from dotenv import load_dotenv

load_dotenv()
import asyncio
import time

from web3 import Web3

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

SWAP_SLIPPAGE_BPS = int(os.getenv("SWAP_SLIPPAGE_BPS", "100"))

_prefix = LOG_PREFIX + " " if LOG_PREFIX else ""


def _addr_probe(addr: str) -> str:
    cs = Web3.to_checksum_address(addr)
    return f"{cs[:10]}…{cs[-6:]}"


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
):
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
        raise RuntimeError(
            "No quotable router path — check liquidity/token addresses (see last router error)."
        ) from last_err

    min_out = max(1, (best_amt * (10000 - min(SWAP_SLIPPAGE_BPS, 9999))) // 10000)
    return best_path, best_amt, min_out


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

        router = Web3.to_checksum_address(ROUTER)

        print(
            f"{_prefix}swap intent | {_addr_probe(token_in_cs)}→{_addr_probe(token_out_cs)} | "
            f"slippage_bps={SWAP_SLIPPAGE_BPS}"
        )

        path_candidates = build_polygon_swap_path_candidates(token_in_cs, token_out_cs)
        chosen_path, expected_out, amount_out_min = _best_quote_path(
            w3,
            router=router,
            amount_in=amount_in,
            paths=path_candidates,
        )
        print(
            f"{_prefix}route | hops={len(chosen_path) - 1} | expected_out≈{expected_out} | min_out={amount_out_min}"
        )

        nonce = w3.eth.get_transaction_count(WALLET)
        approve_contract = w3.eth.contract(address=token_in_cs, abi=ERC20_ABI)
        approve_tx = approve_contract.functions.approve(router, amount_in).build_transaction({
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

        swap_contract = w3.eth.contract(address=router, abi=ROUTER_SWAP_AND_QUOTE_ABI)
        gas_limit = 320000 if len(chosen_path) <= 2 else 520000

        nonce_swap = w3.eth.get_transaction_count(WALLET)
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
        if receipt["status"] == 0:
            print("❌ Swap failed on-chain!")
            return None

        print("✅ Swap confirmed!")
        return swap_hash.hex()

    except Exception as e:
        print(f"❌ Error in approve_and_swap: {e}")
        import traceback

        traceback.print_exc()
        return None
