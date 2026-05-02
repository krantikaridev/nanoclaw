from clean_swap import get_balances
b = get_balances()
print(f"USDT:{b.usdt:.2f} USDC:{b.usdc:.2f} WMATIC:{b.wmatic:.2f} POL:{b.pol:.4f}")
