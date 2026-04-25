import json
from web3 import Web3
import os
from dotenv import load_dotenv

load_dotenv()

WALLET = "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA"
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WMATIC = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"

def get_balances():
    w3 = Web3(Web3.HTTPProvider(os.getenv("RPC")))
    usdt = w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]).functions.balanceOf(WALLET).call() / 1_000_000
    wmatic = w3.eth.contract(address=WMATIC, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]).functions.balanceOf(WALLET).call() / 1e18
    return usdt, wmatic

def calculate_pnl():
    with open("trade_history.json") as f:
        trades = json.load(f)
    
    realized_profit = sum(t["amount_usd"] for t in trades if "WMATIC_TO_USDT" in t["direction"])
    total_bought = sum(t["amount_usd"] for t in trades if "USDT_TO_WMATIC" in t["direction"])
    
    usdt_now, wmatic_now = get_balances()
    wmatic_price = 0.092
    wmatic_value = wmatic_now * wmatic_price
    total_value = usdt_now + wmatic_value
    
    print("\n" + "="*55)
    print("📊 NANOC LAW — PNL REPORT (V2.4)")
    print("="*55)
    print(f"Total Trades Executed : {len(trades)}")
    print(f"Buys (USDT → WMATIC): {len([t for t in trades if 'USDT_TO' in t['direction']])}  → ${total_bought:.2f}")
    print(f"Sells (Profit Taken)  : {len([t for t in trades if 'WMATIC_TO' in t['direction']])}  → ${realized_profit:.2f}")
    print(f"Current USDT Balance  : ${usdt_now:.2f}")
    print(f"Current WMATIC        : {wmatic_now:.2f} (${wmatic_value:.2f})")
    print(f"Total Portfolio Value : ${total_value:.2f}")
    print(f"Realized Profit So Far: ${realized_profit:.2f}")
    print("="*55 + "\n")
    
    return realized_profit, total_value

if __name__ == "__main__":
    calculate_pnl()
