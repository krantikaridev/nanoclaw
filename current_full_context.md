# NanoClaw Grok Context - Trading Bot (as of April 5, 2026)

## Core Goal
Autonomous micro trading on Polygon with 10.88 USDC seed. Run real small USDC → WETH swaps on Uniswap V3, 6x/day via cron, for fast real-world feedback. Compare with paper SIM. Keep tax-compliant logs. Never mix with Hitalent.

## Wallet & Capital
- Wallet: 0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA (Polygon mainnet)
- Real seed: 10.88 USDC (from Binance P2P)
- POL gas: Available (currently ~4.76+ POL)
- Safety rules (strict, never change without discussion):
  - Max trade size: 2.00 USDC
  - Max utilization: 80% (~8.70 USDC deployable)
  - Reserve protected: ~2.18 USDC (untouched)
  - Daily loss cap: ~1 USDC (goal)
- Current real balance: 10.88 USDC (untouched by swaps so far)

## Current Setup
- Main script: `real_parallel_runner.py` (runs via cron every 4 hours)
- Paper SIM: `skills/autonomous-revenue-engine/` (capital.json, X Swarm + SEO/content/gigs, currently ~$163k–$167k and growing)
- Automation: `run_real_trade_cron.sh` via crontab (6x/day)
- Logging: `memory/TAX-AUDIT.md` + `combined_dashboard.md` (auto-updated with size, tx hash, paper capital)
- Environment: `.venv/` (activated in cron wrapper), `.env` for POLYGON_PRIVATE_KEY (never commit)
- Repo: https://github.com/krantikaridev/nanoclaw (main branch)

## What Works Today
- Cron runs autonomously 6x/day
- Private key loads, RPC connects, transactions broadcast successfully (real tx hashes on PolygonScan)
- Safety guards enforced
- Paper SIM runs in parallel and grows
- All activity logged for tax compliance (VDA rules in India)

## Current Limitation (Important)
- Transactions are still **tiny self-send tests** (0.0001 POL).  
- **No real USDC → WETH swap** has occurred yet.  
- Therefore, real seed balance shows no P&L movement. This is the last hurdle.

## Pending Step (One Targeted Change)
Add the actual Uniswap V3 swap call (approve USDC + swapExactTokensForTokens) to `real_parallel_runner.py`.  
After this change:
- Cron will perform real small USDC swaps
- Visible P&L in MetaMask / PolygonScan within hours
- Daily real-world feedback on algo performance vs paper SIM
- Then we monitor for 3–7 days before deciding to scale capital or adjust.

## Communication Preference
Prefer Telegram for daily interaction once fully ready. Until then, SSH is acceptable for quick checks.  
Context file must be referenced at start of any new conversation to avoid hallucination.

Last updated: 2026-04-05
=== STATUS SNAPSHOT Mon Apr  6 15:00:43 UTC 2026 ===
USDC remaining: ✅ Private key loaded — REAL on-chain swap enabled
✅ MAINNET RPC connected: True | URL: https://polygon.drpc.org
💰 Current balances | USDC: 4.4464 | POL (gas): 5.5396
🛡️  MICRO REAL MODE ACTIVE | Max trade: 2.0 USDC | Daily loss limit: 1.0 USDC
4.446393
POL gas: ✅ Private key loaded — REAL on-chain swap enabled
✅ MAINNET RPC connected: True | URL: https://polygon.drpc.org
💰 Current balances | USDC: 4.4464 | POL (gas): 5.5396
🛡️  MICRO REAL MODE ACTIVE | Max trade: 2.0 USDC | Daily loss limit: 1.0 USDC
5.539575824988068
Wallet: 0x6e291a7180bD198d67Eeb792Bb3262324D3e64AA
Last txs: Check PolygonScan for wallet
Trades today: 7
=== NIGHT PAUSE Mon Apr  6 19:00:38 UTC 2026 ===
Portfolio: 1.31 (+3.27%)
USDC: 2.746 | WETH: 0.00844 (~8.07)
Trades tonight: 5 (total many today)
=== DAILY SNAPSHOT Mon Apr 13 16:19:08 UTC 2026 ===
Portfolio: ~7
USDT: ~34.86
SIM capital: ~343k (positive)
Strategy: Baseline + SIM confidence gate
=== DAY END SNAPSHOT Mon Apr 13 18:07:44 UTC 2026 ===
Portfolio: 9.01 | USDT: 34.36
Strategy files: real_parallel_runner.py + strategy_polymarket.py
