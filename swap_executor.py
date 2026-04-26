import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
import time
from web3 import Web3
from constants import WALLET, USDT, WMATIC, ROUTER, ROUTER_ABI, ERC20_ABI

async def approve_and_swap(w3, private_key, amount_in: int, direction="USDT_TO_WMATIC"):
    print(f"🚀 Executing REAL swap: {direction} | Amount: {amount_in}")

    try:
        if direction == "USDT_TO_WMATIC":
            token_in = USDT
            token_out = WMATIC
        else:
            token_in = WMATIC
            token_out = USDT

        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)
        router = Web3.to_checksum_address(ROUTER)

        # Approve
        nonce = w3.eth.get_transaction_count(WALLET)
        approve_contract = w3.eth.contract(address=token_in, abi=ERC20_ABI)
        approve_tx = approve_contract.functions.approve(router, amount_in).build_transaction({
            "from": WALLET,
            "nonce": nonce,
            "gas": 140000,
            "gasPrice": w3.eth.gas_price * 15 // 10,
            "chainId": 137
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, os.getenv("PRIVATE_KEY"))
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"✅ Approve Tx: {approve_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=300)
        if receipt["status"] == 0:
            print("❌ Approve failed!")
            return None
        print("✅ Approve confirmed!")
        await asyncio.sleep(5)

        # Swap
        swap_contract = w3.eth.contract(address=router, abi=ROUTER_ABI)
        path = [token_in, token_out]

        nonce_swap = w3.eth.get_transaction_count(WALLET)
        swap_tx = swap_contract.functions.swapExactTokensForTokens(
            amount_in,
            0,
            path,
            WALLET,
            int(time.time()) + 300
        ).build_transaction({
            "from": WALLET,
            "nonce": nonce_swap,
            "gas": 300000,
            "gasPrice": w3.eth.gas_price * 15 // 10,
            "chainId": 137
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, os.getenv("PRIVATE_KEY"))
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
