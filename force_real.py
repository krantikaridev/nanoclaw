"""FORCE REAL MODE - Last attempt to register handlers"""
print("🔥 FORCE REAL MODE LOADER STARTED", flush=True)

try:
    from skills.micro_real_mode import enable_micro_real, micro_safe_cycle
    from telegram.ext import CommandHandler

    # Global registration
    application.add_handler(CommandHandler("enable_micro_real", enable_micro_real))
    application.add_handler(CommandHandler("micro_safe_cycle", micro_safe_cycle))
    print("✅ SUCCESS: Real mode handlers registered globally from force_real.py", flush=True)
except Exception as e:
    print(f"❌ FAILED to register: {e}", flush=True)
    import traceback
    print(traceback.format_exc(), flush=True)
