# Nanoclaw v2 - AI Context (Single Source of Truth)

**Repo**: https://github.com/krantikaridev/nanoclaw  
**Active Branch**: V2  
**Date**: 28 April 2026

**Current Portfolio Snapshot**:
- Total ≈ $113
- WMATIC: ~77% ($79.54)
- USDT: $33.48
- POL: $5.00

**Goal**: $100,000 by 31 May 2026 with max 20% drawdown.

**Key .env Settings**:
- COPY_TRADE_PCT=0.12 (12%)
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

**Current Status**:
- Bot running cleanly on cron every 10 min
- No more RPC crashes
- Realized profit still low (needs more aggressive triggering + high-vol assets)
- **USDCopyStrategy NOT YET INTEGRATED into main loop** (critical blocker)
- **NEW OPPORTUNITY**: Tokenized equity trading (GOOGLON, MSFTON, APPLON, AMZNON) now available on the same DEX – earnings week volatility play

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
1. Integrate USDCopyStrategy into clean_swap.py (immediate)
2. Add Tokenized Equity / Earnings Trader strategy (GOOGLON etc.)
3. Wallet scoring v2 (earnings performance + volume)
4. Scale to $300-500 this week
