# Nanoclaw v2 - AI Context (Single Source of Truth)

**Repo**: https://github.com/krantikaridev/nanoclaw  
**Active Branch**: V2 (short & stable)  
**Date**: 28 April 2026

**Current Portfolio Snapshot**:
- Total ≈ $113
- WMATIC: ~77% ($79.54 / 865 WMATIC)
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
- RPC=https://polygon.publicnode.com (stable free endpoint)

**Current Status**:
- ✅ Cron fixed (clean_swap.py runs without errors)
- ✅ Protection module + copy trading active
- Profit-taking logic now functional (8%/12% TP + 5% trailing)

**Pending**:
- Realized profit still low
- Heavy WMATIC concentration
- No USDC strategy yet
- Gas protection needs proper implementation

**Design Rules**:
- Builder Pattern + Functional Composition
- 100% .env driven
- Unit testable from day one
- Risk-first

**How to Continue in Any New Thread**:
Paste this raw URL at the very top:
https://raw.githubusercontent.com/krantikaridev/nanoclaw/V2/AI_CONTEXT.md

Then describe what you want to do next.

**Next Milestone**: Clean modular v2.7 + Cursor development
