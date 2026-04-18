import asyncio
from web3 import Web3
from dotenv import load_dotenv
import os
from datetime import datetime
load_dotenv()

WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY")
RPC = "https://rpc.ankr.com/polygon"
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WETH = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"
ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

w3 = Web3(Web3.HTTPProvider(RPC))
print("RPC:", w3.is_connected())

bal = w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}]).functions.balanceOf(WALLET).call() / 10**6
print("Real USDT:", bal)

async def swap():
    amount = 2_000_000
    router = w3.eth.contract(address=ROUTER, abi=[{"inputs":[{"components":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"fee","type":"uint24"},{"name":"recipient","type":"address"},{"name":"deadline","type":"uint256"},{"name":"amountIn","type":"uint256"},{"name":"amountOutMinimum","type":"uint256"},{"name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"name":"","type":"uint256"}],"stateMutability":"payable","type":"function"}])

    params = {
        "tokenIn": USDT,
        "tokenOut": WETH,
        "fee": 500,
        "recipient": WALLET,
        "deadline": int(datetime.now().timestamp()) + 600,
        "amountIn": amount,
        "amountOutMinimum": 0,
        "sqrtPriceLimitX96": 0
    }

    tx = router.functions.exactInputSingle(params).build_transaction({
        'from': WALLET,
        'gas': 400000,
        'gasPrice': w3.to_wei('400', 'gwei'),
        'nonce': w3.eth.get_transaction_count(WALLET),
    })

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print("✅ REAL TX HASH:", tx_hash.hex())
    print("https://polygonscan.com/tx/" + tx_hash.hex())

asyncio.run(swap())
