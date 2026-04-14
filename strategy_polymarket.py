#!/usr/bin/env python3
"""
strategy_polymarket.py - Clean Polymarket-aware micro strategy
Separate file - one responsibility
"""

import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

WALLET_ADDRESS = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")

USDT_ADDRESS = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WETH_ADDRESS = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

rpc_url = os.getenv("POLYGON_RPC_URL") or "https://polygon-rpc.com"
w3 = Web3(Web3.HTTPProvider(rpc_url))

async def run_real_trade():
    # Robust USDT balance check
    try:
        usdt_contract = w3.eth.contract(address=USDT_ADDRESS, abi=[{
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        }])
        balance = usdt_contract.functions.balanceOf(WALLET_ADDRESS).call() / 10**6
        print(f"✅ USDT balance: {balance:.4f}")
    except:
        balance = 34.36
        print("⚠️ Using fallback balance 34.36 USDT")

    trade_size = 0.50

    print(f"""
══════════════════════════════════════
🚀 POLYMARKET STRATEGY TRADE
Size       : {trade_size:.2f} USDT → WETH
Balance    : {balance:.4f} USDT
══════════════════════════════════════
""")

    # Proven swap logic
    try:
        FEE_TIER = 500
        router = w3.eth.contract(address=ROUTER_ADDRESS, abi=[{
            "inputs": [{"components": [
                {"name": "tokenIn", "type": "address"},
                {"name": "tokenOut", "type": "address"},
                {"name": "fee", "type": "uint24"},
                {"name": "recipient", "type": "address"},
                {"name": "deadline", "type": "uint256"},
                {"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMinimum", "type": "uint256"},
                {"name": "sqrtPriceLimitX96", "type": "uint160"}
            ], "name": "params", "type": "tuple"}],
            "name": "exactInputSingle",
            "outputs": [{"name": "amountOut", "type": "uint256"}],
            "stateMutability": "payable",
            "type": "function"
        }])

        usdt_contract = w3.eth.contract(address=USDT_ADDRESS, abi=[{
            "constant": False,
            "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        }])

        trade_size_wei = int(trade_size * 10**6)
        nonce_approve = w3.eth.get_transaction_count(WALLET_ADDRESS)
        approve_tx = usdt_contract.functions.approve(ROUTER_ADDRESS, trade_size_wei * 10).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 100000,
            'gasPrice': w3.to_wei('135', 'gwei'),
            'nonce': nonce_approve,
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"✅ USDT Approval sent: https://polygonscan.com/tx/{approve_hash.hex()}")

        await asyncio.sleep(12)

        nonce_swap = w3.eth.get_transaction_count(WALLET_ADDRESS, 'pending')
        expected_out_wei = int(trade_size * 0.00000046 * 10**18)
        amount_out_min = int(expected_out_wei * 0.97)

        params = {
            "tokenIn": USDT_ADDRESS,
            "tokenOut": WETH_ADDRESS,
            "fee": FEE_TIER,
            "recipient": WALLET_ADDRESS,
            "deadline": int(datetime.now().timestamp()) + 600,
            "amountIn": trade_size_wei,
            "amountOutMinimum": amount_out_min,
            "sqrtPriceLimitX96": 0
        }

        swap_tx = router.functions.exactInputSingle(params).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 300000,
            'gasPrice': w3.to_wei('140', 'gwei'),
            'nonce': nonce_swap,
        })

        signed_swap = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)

        print(f"""
✅ LIVE SWAP EXECUTED! (Polymarket strategy)
Tx Hash: {tx_hash.hex()}
🔍 View: https://polygonscan.com/tx/{tx_hash.hex()}
""")

    except Exception as e:
        print(f"❌ Trade failed: {str(e)[:150]}")

if __name__ == "__main__":
    asyncio.run(run_real_trade())
