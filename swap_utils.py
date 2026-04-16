#!/usr/bin/env python3
"""
Nanoclaw v2 - Shared Swap Utility (Madan Pune)
Used by all strategies to execute trades consistently
"""

import asyncio
from datetime import datetime
from web3 import Web3

async def execute_usdt_to_weth_swap(w3, wallet_address, private_key, trade_size_usdt=2.0, slippage_pct=4.0):
    """
    Reusable function for USDT → WETH swap on Uniswap V3
    Returns tx_hash or None on failure
    """
    try:
        USDT_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
        WETH_ADDRESS = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
        ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

        usdt_contract = w3.eth.contract(address=USDT_ADDRESS, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}])
        usdt_balance = usdt_contract.functions.balanceOf(wallet_address).call() / 10**6

        if usdt_balance < trade_size_usdt:
            print(f"❌ INSUFFICIENT USDT: {usdt_balance:.4f}")
            return None

        router = w3.eth.contract(address=ROUTER_ADDRESS, abi=[{"inputs":[{"components":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"fee","type":"uint24"},{"name":"recipient","type":"address"},{"name":"deadline","type":"uint256"},{"name":"amountIn","type":"uint256"},{"name":"amountOutMinimum","type":"uint256"},{"name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}])

        # Approve
        approve_tx = usdt_contract.functions.approve(ROUTER_ADDRESS, int(trade_size_usdt * 10**6 * 10)).build_transaction({
            'from': wallet_address,
            'gas': 150000,
            'gasPrice': w3.to_wei('140', 'gwei'),
            'nonce': w3.eth.get_transaction_count(wallet_address),
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, private_key)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"✅ Approval sent: https://polygonscan.com/tx/{approve_hash.hex()}")
        await asyncio.sleep(8)

        # Swap
        params = {
            "tokenIn": USDT_ADDRESS,
            "tokenOut": WETH_ADDRESS,
            "fee": 500,
            "recipient": wallet_address,
            "deadline": int(datetime.now().timestamp()) + 600,
            "amountIn": int(trade_size_usdt * 10**6),
            "amountOutMinimum": int(trade_size_usdt * 10**6 * (1 - slippage_pct/100)),
            "sqrtPriceLimitX96": 0
        }
        swap_tx = router.functions.exactInputSingle(params).build_transaction({
            'from': wallet_address,
            'gas': 300000,
            'gasPrice': w3.to_wei('140', 'gwei'),
            'nonce': w3.eth.get_transaction_count(wallet_address, 'pending'),
        })
        signed_swap = w3.eth.account.sign_transaction(swap_tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)

        print(f"✅ Swap executed! Tx: {tx_hash.hex()}")
        return tx_hash.hex()

    except Exception as e:
        print(f"❌ Swap failed: {e}")
        return None
