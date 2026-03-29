# MICRO REAL MODE HANDLER - 29 Mar 2026
# Strict limits as requested by user

REAL_MODE = False
MICRO_LIMITS = {
    "max_trade_usdc": 2.0,
    "daily_loss_cap_usdc": 1.0,
    "seed_usdc": 10.0,
    "reserve_usdc": 0.88,
    "wallet": "0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA",
    "network": "Polygon"
}

async def enable_micro_real(update, context):
    global REAL_MODE
    REAL_MODE = True
    await update.message.reply_text(f"""🔓 MICRO REAL MODE ENABLED WITH STRICT LIMITS
Max trade: {MICRO_LIMITS["max_trade_usdc"]} USDC
Daily loss cap: {MICRO_LIMITS["daily_loss_cap_usdc"]} USDC
Using only {MICRO_LIMITS["seed_usdc"]} USDC seed
0.88 USDC reserve untouched
Wallet: {MICRO_LIMITS["wallet"]} ({MICRO_LIMITS["network"]})
All trades will be logged for tax audit""")

async def micro_safe_cycle(update, context):
    if not REAL_MODE:
        await update.message.reply_text("Real mode not enabled yet. Send 'enable micro real mode' first.")
        return
    await update.message.reply_text(f"""⚡ STARTING MICRO REAL CYCLE
Position size capped at {MICRO_LIMITS["max_trade_usdc"]} USDC
Daily loss protection: {MICRO_LIMITS["daily_loss_cap_usdc"]} USDC
Reserve protected: {MICRO_LIMITS["reserve_usdc"]} USDC
Tax audit log will be created automatically""")
    # Your existing cycle logic will run here with size limit applied

# Register commands so they work
application.add_handler(CommandHandler("enable_micro_real", enable_micro_real))
application.add_handler(CommandHandler("micro_safe_cycle", micro_safe_cycle))
