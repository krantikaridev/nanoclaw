"""Real Mode Loader - Forces registration on bot startup"""
try:
    from micro_real_mode import enable_micro_real, micro_safe_cycle
    from telegram.ext import CommandHandler

    # Register the handlers globally
    application.add_handler(CommandHandler("enable_micro_real", enable_micro_real))
    application.add_handler(CommandHandler("micro_safe_cycle", micro_safe_cycle))
    print("✅ Real mode handlers registered successfully from loader", flush=True)
except Exception as e:
    print(f"⚠️ Real mode loader failed: {e}", flush=True)
    import traceback
    print(traceback.format_exc(), flush=True)
