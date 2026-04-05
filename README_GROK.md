# NanoClaw Trading Bot - Grok Context (as of 31 Mar 2026)

## Wallet & Capital
- Polygon wallet: 0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA
- Real capital: 10.88 USDC (initial seed)
- Reserve to protect: ~2.18 USDC (80% utilization max)
- Max trade size: 2.00 USDC
- Daily loss cap: ~1 USDC

## Current Setup
- Paper sim: Running in skills/autonomous-revenue-engine/ with X Swarm + content/SEO/gigs
- Real executor: real_parallel_runner.py (cron every 4 hours, 6x/day)
- Automation: run_real_trade_cron.sh via crontab
- Logging: combined_dashboard.md, memory/TAX-AUDIT.md, real_cron.log
- .env used for private key (never commit)

## Goals
- Fast feedback on real trades (short-term positions preferred)
- Parallel paper vs real comparison
- Tax compliant logging (VDA rules in India)
- Scale only after proven real P&L

## Separation Rule
- Trading bot stays completely separate from Hitalent.in
- Hitalent has its own thread and README_HITALENT.md

Last updated: 2026-03-31
