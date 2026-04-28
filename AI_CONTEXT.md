# Nanoclaw v2 - AI Context (Single Source of Truth)

**Repo**: https://github.com/krantikaridev/nanoclaw  
**Active Branch**: V2  
**Date**: 28 April 2026
**Wallet**: 0x6e291a7180bd198d67eeb792bb3262324d3e64aa

**Current Portfolio Snapshot**:
- Total ≈ $113
- WMATIC: ~77% ($79.54)
- USDT: $33.48
- POL: $5.00

**Goal**: $100,000 by 31 May 2026 with max 20% drawdown.

**Key .env Settings**:
- COPY_TRADE_PCT=0.25 (25%)
- COPY_COOLDOWN=90
- MAX_EXPOSURE_PCT=65
- TRAILING_STOP_PCT=5.0
- TAKE_PROFIT_PCT=8.0
- STRONG_SIGNAL_TP=12.0
- RPC=https://polygon.publicnode.com
- refer .env.local for details

**Recent Improvements**:
- ✅ Gas Protector module fully integrated (GasProtector.builder())
- ✅ Profit-taking logic improved (8%/12% TP + 5% trailing)
- ✅ Code cleanup + unit tests added
- ✅ Repo cleaned (old v25_*, memory/, skills/, xwatcher/ archived)
- ✅ USDCopyStrategy module completed (builder + gas-protected + per-wallet cooldown)
- ✅ Agent Feedback Loop completed
- ✅ Tokenized Equity + X-Signal multi-asset trader scaffolded (dynamic asset list + per-asset cooldown + gas-protected)

**Current Status**:
- Bot running on VM with **MAX_GWEI=450**
- Local development in Cursor + periodic `git pull` on VM
- X-Signal Equity Trader fully integrated and firing. 3 test assets added. Aggression at 25%. Realized profit +$74 in USDT.
- Tokenized equity opportunity remains high-priority (earnings week volatility play)

## Development Workflow

- Local Cursor → implement changes → run required checks → **single commit**
- Review locally → push manually
- VM: `git stash` → `git pull` → re-apply stash (as needed) → restart cron/runtime

## Automation Plan

- Telegram **PnL** notifications
- Telegram **trade alerts** (entries/exits + gas status)

## Tokenized Equity + X-Signal Multi-Asset Trader

- **What**: On-chain tokenized equities (e.g., `GOOGLON`, `MSFTON`, `APPLON`, `AMZNON`) traded via the same router path.
- **Input**: X-Signal “expert” strength per asset + earnings proximity; no fixed “4-stock” limit (dynamic list from `followed_equities.json`).
- **Behavior**: Protection/Profit always win; then strong X-Signal equity entries/exits; then USDC-copy; then legacy logic.
- **Risk controls**: Gas-protected + per-asset cooldown; higher strong TP target (15%) due to equity volatility.

**Tokenized Equity Opportunity (28 Apr 2026)**:
- GOOGLON / MSFTON / APPLON / AMZNON = on-chain synthetic US stocks
- This week = major earnings (GOOGL, MSFT, AAPL, AMZN)
- 15-40% moves expected → perfect for our TP engine
- Same execution path (USDT/USDC → XXXXON)
- New milestone: Add Earnings Trader strategy + earnings calendar

**Environment Notes**:
- Use the project virtualenv before running Python commands: `cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate`
- Prefer venv-backed commands for manual runs/tests so project dependencies resolve correctly

**Design Rules**:
- Builder Pattern + Functional Composition
- 100% .env driven
- Unit testable from day one
- Risk-first

**How to Continue in Any New Thread**:
Paste this raw URL at the top:
https://raw.githubusercontent.com/krantikaridev/nanoclaw/V2/AI_CONTEXT.md

**Next Milestone**:
- X-Signal Equity Trader live + Agent Feedback auto-generation + Telegram notifications + First real tokenized stock trade this week
