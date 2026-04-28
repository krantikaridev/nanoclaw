# Autonomous Revenue Engine 🤑

## Description
Simulates full revenue cycle with 12 CashClaw skill ports (paper trading $10k virtual capital). 
Runs every 2h via cron or on command (\"cycle now\"). 
Uses Grok-4 subagents for optimization. Self-improves via CLAUDE.md lessons.

## Usage
- `python3 engine.py`: Single cycle
- Manual triggers: \"cycle now\", \"iterate\"
- Cron: Auto every 2h (ID: 3f46da21)

## Cycle Steps
1. **Scan**: Polymarket vol/edge, gigs, X trends (skills)
2. **Execute**: Sim trades/content/leadgen (random/profit sim)
3. **Profit Calc**: +5-20% per cycle (Grok opt)
4. **Report**: Update capital.json, append CLAUDE.md, Telegram msg
5. **Improve**: Lessons → next cycle

## Files
- `engine.py`: Main logic (load/save capital, run ports)
- `ports/`: 12 skill stubs (polymarket_analyzer.py etc.)
- `capital.json`: {\"capital\": 14820, \"timestamp\": \"...\"}
- `../../groups/revenue/CLAUDE.md`: Strategy/lessons

## Status
Paper mode: $10k → $14.8k (5 cycles). Real pending: USDC wallet/Stripe keys.

---
*Powered by Repo-Guardian: Readable forever. Indentation perfect.*