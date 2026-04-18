#!/usr/bin/env python3
import asyncio
from web3 import Web3
from dotenv import load_dotenv
import os
from datetime import datetime
load_dotenv()

WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = "https://polygon-rpc.com"
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

w3 = Web3(Web3.HTTPProvider(RPC))
print("RPC connected:", w3.is_connected())
print("USDT balance:", w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}]).functions.balanceOf(WALLET).call() / 10**6)

async def swap():
    amount = 2_000_000
    # ... V3 exactInputSingle params/gas 350gwei ...
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print("✅ REAL TX HASH:", tx_hash.hex())
    print("https://polygonscan.com/tx/" + tx_hash.hex())

asyncio.run(swap())
=== END OF FILE PREVIEW ===
