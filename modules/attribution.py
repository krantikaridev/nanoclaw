"""Per-trade PnL attribution (high-ROI learning)"""
def log_trade_attribution(asset, size, signal, copied_wallet, expected_pnl):
    print(f"TRADE_ATTRIBUTION | Asset={asset} | Size=${size:.2f} | Signal={signal:.2f} | Wallet={copied_wallet or 'X-SIGNAL'} | Expected_PnL={expected_pnl:.2f}")
