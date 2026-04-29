# Nanoclaw v2 - AI Context (Single Source of Truth)

**Repo**: https://github.com/krantikaridev/nanoclaw  
**Active Branch**: V2  
**Date**: 29 April 2026
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
- ENABLE_X_SIGNAL_EQUITY=true
- X_SIGNAL_EQUITY_MIN_STRENGTH=0.70
- refer .env.local for overrides

**Recent Improvements**:
- ✅ Gas Protector module fully integrated (GasProtector.builder())
- ✅ Profit-taking logic improved (8%/12% TP + 5% trailing)
- ✅ Code cleanup + unit tests added
- ✅ Repo cleaned (old v25_*, memory/, skills/, xwatcher/ archived)
- ✅ USDCopyStrategy module completed (builder + gas-protected + per-wallet cooldown)
- ✅ Agent Feedback Loop completed
- ✅ Tokenized Equity + X-Signal multi-asset trader scaffolded (dynamic asset list + per-asset cooldown + gas-protected)

**Current issues addressed (2026-04-29 — uncommitted change set)**:
- **X-Signal equity**: `SignalEquityTrader` is now invoked from `determine_trade_decision` via `try_x_signal_equity_decision()`: loads `followed_equities.json`, filters by `min_signal_strength` vs `X_SIGNAL_EQUITY_MIN_STRENGTH`, iterates eligible assets by strength, and returns the first valid `EquityTradePlan` (highest signal first). Previously the module object existed but decision flow did not consistently call it with the same rules as the JSON list.
- **followed_equities.json**: Removed invalid placeholder addresses; filled with canonical **Ethereum** Ondo Global Markets ERC-20s (GOOGLON, NVDAON, MSFTON) per Etherscan/CoinGecko references, plus `_polygon_note` explaining that these tickers are not officially deployed on Polygon POS yet—override `address` (or env) with Polygon contracts when executing purely on chain 137.
- **Observability**: Balance snapshot at each decision, explicit `🔍 DECISION PATH` tags (PROTECTION, PROFIT_TAKE, X_SIGNAL_EQUITY, USDC_COPY, POLYCOPY, MAIN_STRATEGY), and structured X-Signal logs (`X-SIGNAL EQUITY CHECK | …`, `ACTIVE | …`, `No valid plan … (reason: …)`).
- **Env**: `ENABLE_X_SIGNAL_EQUITY` and `X_SIGNAL_EQUITY_MIN_STRENGTH` added to `.env`, `.env.example`, and `.env.local`; `load_dotenv(".env.local", override=True)` so local flags load after `.env`.
- **USDT↔WMATIC only**: Root cause was X-Signal path not driving decisions and/or zero USDC / wrong token addresses; equity legs need USDC for buys and valid `token_in`/`token_out` for `approve_and_swap`. Main strategy remains USDT/WMATIC when no higher-priority path fires.

**Current Status**:
- Bot running on VM with **MAX_GWEI=450**
- Local development in Cursor + periodic `git pull` on VM
- X-Signal equity path is wired into `determine_trade_decision` with logging; production behavior still depends on USDC balance, gas guard, cooldowns, and Polygon-appropriate equity contract addresses when swapping on 137.
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
- Harden Polygon-native or bridged contract addresses for followed equities (per-asset `address` or env when Ondo/bridge lists them for chain 137), validate router path (USDC→equity may need multi-hop), Agent Feedback auto-generation, Telegram notifications, first live tokenized equity swap on Polygon after liquidity checks
