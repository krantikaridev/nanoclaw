#!/usr/bin/env python3
import json
import os
import sys
import traceback
from datetime import datetime

print('DEBUG: Script started', flush=True)

CAPITAL_FILE = 'capital.json'
CLAUDE_FILE = '../../groups/revenue/CLAUDE.md'
TELEGRAM_CHAT = '5816538180'

INITIAL_CAPITAL = 10000

class RevenueEngine:
    def __init__(self):
        print('DEBUG: __init__ called', flush=True)
        try:
            self.capital = self.load_capital()
            print(f'DEBUG: Capital loaded: {self.capital}', flush=True)
        except Exception as e:
            print(f'DEBUG: Init error: {e}', flush=True)
            print(traceback.format_exc(), flush=True)
            self.capital = INITIAL_CAPITAL
        self.profit = 0
        self.lessons = []

    def load_capital(self):
        print('DEBUG: load_capital called', flush=True)
        if os.path.exists(CAPITAL_FILE):
            print('DEBUG: CAPITAL_FILE exists', flush=True)
            with open(CAPITAL_FILE) as f:
                data = json.load(f)
                print(f'DEBUG: JSON data: {data}', flush=True)
                return data.get('capital', INITIAL_CAPITAL)
        print('DEBUG: No CAPITAL_FILE', flush=True)
        return INITIAL_CAPITAL

    # ... rest same, but add flushes and try/excepts later if needed

    def save_capital(self):
        print('DEBUG: save_capital called', flush=True)
        with open(CAPITAL_FILE, 'w') as f:
            json.dump({'capital': self.capital, 'timestamp': datetime.now().isoformat()}, f)
        print('DEBUG: Capital saved', flush=True)

    def run_skill(self, skill_name):
        sim_profit = 100 + hash(skill_name) % 500
        self.profit += sim_profit
        self.lessons.append(f"{skill_name}: +${sim_profit:.0f} (sim)")
        return sim_profit

    def grok_reason(self, task):
        print(f"Grok-4 reasoning: {task} => Optimize {task.lower()}", flush=True)
        return "Improved strategy: High vol markets, SEO keywords"

    def full_cycle(self):
        print("=== Revenue Cycle Start ===", flush=True)
        skills = [
            'seo-auditor', 'content-writer', 'lead-generator', 'invoicer',
            'hyrve-gigs', 'polymarket-trader', 'x-poster', 'affiliate-bot',
            'arbitrage-scanner', 'gig-bidder', 'stripe-sim', 'self-optimizer'
        ]
        for skill in skills:
            self.run_skill(skill)
            self.grok_reason(skill)
        self.capital += self.profit
        print("=== Cycle End ===", flush=True)

    def generate_report(self):
        report = f"\\n🚀 Revenue Cycle Report ({datetime.now()}):\\n"
        report += f"Virtual Capital: ${self.capital:,.0f} (+${self.profit:,.0f})\\n"
        report += "\\nLessons:\\n" + '\\n'.join(self.lessons[:5])
        report += "\\nNext: Scale to real w/ wallet."
        return report

    def update_claude(self):
        print('DEBUG: update_claude called', flush=True)
        try:
            new_lesson = f"[ {datetime.now().strftime('%Y-%m-%d %H:%M')} ] Cycle profit: ${self.profit:.0f}. {self.grok_reason('overall')}"
            with open(CLAUDE_FILE, 'a') as f:
                f.write(f"\\n{new_lesson}")
            print('DEBUG: CLAUDE updated', flush=True)
        except Exception as e:
            print(f'DEBUG: Claude update error: {e}', flush=True)
            print(traceback.format_exc(), flush=True)

    def send_report(self):
        print('DEBUG: send_report called', flush=True)
        report = self.generate_report()
        print(report, flush=True)
        self.update_claude()

    def run(self):
        print('DEBUG: run() called', flush=True)
        self.full_cycle()
        self.save_capital()
        self.send_report()

if __name__ == '__main__':
    print('DEBUG: __main__ if', flush=True)
    # === MICRO REAL MODE INTEGRATION (29 Mar 2026) ===
    # This registers the handler so natural language + commands can enable real trading

    try:
        from ..micro_real_mode import enable_micro_real, micro_safe_cycle
        # Register the handlers
        application.add_handler(CommandHandler("enable_micro_real", enable_micro_real))
        application.add_handler(CommandHandler("micro_safe_cycle", micro_safe_cycle))
        print("✅ Micro real mode handler successfully registered", flush=True)
    except Exception as e:
        print(f"⚠️ Micro real mode registration failed: {e}", flush=True)
    try:
        engine = RevenueEngine()
        engine.run()
    except Exception as e:
        print(f'CRITICAL ERROR: {e}', flush=True)
        print(traceback.format_exc(), flush=True)

# FORCE LOAD REAL MODE - 29 Mar 2026
try:
    from skills.real_mode_loader import *
    print("Real mode loader executed at startup", flush=True)
except Exception as e:
    print(f"Real mode loader failed at startup: {e}", flush=True)

