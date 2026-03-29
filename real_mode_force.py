"""Force Real Mode Loader - Run at startup"""
print("🔥 Force Real Mode Loader Started", flush=True)

try:
    from skills.micro_real_mode import enable_micro_real, micro_safe_cycle
    from telegram.ext import CommandHandler

    application.add_handler(CommandHandler("enable_micro_real", enable_micro_real))
    application.add_handler(CommandHandler("micro_safe_cycle", micro_safe_cycle))
    print("✅ SUCCESS: Micro real mode handlers registered globally", flush=True)
except Exception as e:
    print(f"❌ FAILED to register real mode: {e}", flush=True)
    import traceback
    print(traceback.format_exc(), flush=True)
