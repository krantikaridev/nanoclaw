# Simple hook to call real executor from Telegram
async def run_real_trade(update, context):
    size = 1.0  # default
    if context.args:
        try:
            size = float(context.args[0])
        except:
            size = 1.0
    await update.message.reply_text(f"Triggering real trade of {size} USDC...")
    # Call the real executor
    from real_parallel_runner import run_real_trade as exec_trade
    await exec_trade(size)

print("✅ Real Telegram hook loaded", flush=True)
