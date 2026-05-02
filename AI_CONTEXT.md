# Nanoclaw v2 - AI Context (Single Source of Truth)
## V2.5.3 Status (as of 1 May 2026, 13:30 IST)

**Current Situation**:
- Portfolio: ~$101.25 (stable, no major loss)
- All Tier 1 improvements deployed: Dynamic position sizing, 1inch aggregator, 4 assets (WMATIC_ALPHA, WETH_ALPHA, WBTC_ALPHA, LINK_ALPHA)
- X-SIGNAL currently blocked by high gas (610 gwei > 450 limit) — protection module working correctly
- Global cooldown reduced to 4 minutes, per-asset cooldown = 30 minutes
- `portfolio_history.csv` now shows correct real values (~$95)

**Key Learnings Today**:
- High gas days completely block X-SIGNAL (protection is working as designed)
- Dynamic sizing + 1inch should improve execution once gas normalizes
- 4-minute global cooldown significantly increases cycle frequency

**Next Priority**: Wait for gas to drop below 450 gwei, then observe PnL for 24 hours before any further changes.

**Production Strategy**:
- `main` branch = Production (serious capital)
- `dev` branch = Experimentation ($100 seed)

**Repo**: https://github.com/krantikaridev/nanoclaw  
**Active Branch**: V2  
**Date**: 29 April 2026  
**Wallet**: 0x6e291a7180bd198d67eeb792bb3262324d3e64aa

**Current Status**:
- V2.5.3 - Max Aggression + Bug Fixes in progress.
- V2.5.3 critical findings (1 May 2026): portfolio drawdown to ~$102.19, X-SIGNAL blocked by false guard + low USDC floor mismatch, stale `portfolio_history.csv` totals, hardcoded per-asset cooldown, and TP default drift in logs.

**Current Portfolio Snapshot** (historical baseline; reconcile with balances on-chain):
- Total ≈ $113
- WMATIC: ~77%
- Mix of USDT / POL as configured in live `.env`

**Goal**: Growth with strict risk controls (`protection.py`, GasProtector, take-profit tiers).

## P0 objective (ROI-first)

- **Primary objective:** prove stage strategy can produce **reliable positive net PnL** with trustworthy accounting.
- **Current phase:** stage-only validation on small capital; production scaling is blocked until stage criteria pass.
- **Definition of done for this phase (all required):**
  - Continuous run window: **>= 168 hours (7 days)**
  - Sample size: **>= 40 executed swaps**
  - Net result: **> +2%** over the validation window (net of gas/slippage)
  - Risk cap: **max drawdown < 10%**
  - Data quality: portfolio/trade logs are internally consistent and reproducible

## P0 execution loop (daily)

- Keep one write-enabled stage bot running continuously (do not interrupt data collection unless blocker).
- Prioritize only changes that improve one of:
  - net edge (PnL)
  - risk control integrity
  - data reliability/observability
- Avoid broad refactors during data collection unless they remove a proven blocker.
- At the end of each day, capture:
  - executed swaps count
  - net PnL %
  - max drawdown %
  - top 1-3 blockers for next iteration

## Core strategy (`clean_swap.py` precedence)

Protection → Profit take (`evaluate_take_profit`) → **X-Signal equities** (`try_x_signal_equity_decision`) → USDC copy → polycopy/target wallets → main USDT↔WMATIC logic.

Operational focus: correctness of this precedence, USDC liquidity for equity **buys**, and execution on Polygon **chain ID 137** only.

## Execution & observability

- **`followed_equities.json`**: `min_signal_strength` in JSON and `X_SIGNAL_EQUITY_MIN_STRENGTH` in env both apply — **effective floor = max(JSON, env)**. Logged each X-Signal check as `[nanoclaw] X-Signal threshold …`.
- **Polygon test proxies**: current repo config uses Polygon-native staples (WMATIC / WETH / WBTC) plus `_note` where Ondo tickers remain off-chain-Polygon until official listings; replace `address` when real Polygon contracts exist.
- **Logs**: `[nanoclaw]` prefix via env `LOG_PREFIX`; cycle banner; path tags (`🔍 DECISION PATH`). X-Signal emits threshold line, ACTIVE lines, SUMMARY line, and (when a plan exists) checksum `token_in` / `token_out` before swap.
- **Cooldowns**: per-asset and per-wallet marks run **after a successful on-chain swap** (`approve_and_swap` returns tx hash), not when a plan is merely built (`SignalEquityTrader.build_plan`, `USDCopyStrategy.build_plan`).
- **Global cooldown**: skips full cycle until `COOLDOWN_MINUTES` since `last_run`; log prints approximate seconds remaining.

## **`swap_executor.approve_and_swap`**

- Rejects **`token_in == token_out`** (misconfiguration / wrong `USDC` env).
- **`getAmountsOut`** quote on Router with combined ABI (`ROUTER_SWAP_AND_QUOTE_ABI`); tries **direct** path first, then **WMATIC hop**, then **USDC hop** between non-endpoint intermediates (`build_polygon_swap_path_candidates`).
- **`swapExactTokensForTokens`** uses **`amount_out_min`** from quoted output × `(1 - SWAP_SLIPPAGE_BPS/10000)` (default slippage 1%; env `SWAP_SLIPPAGE_BPS`). Longer paths use higher gas limits.
- **Directions** without explicit tokens: backward-compatible resolutions for USDT/WPOL paths; equity directions supply `token_in` / `token_out` from plans.

## **Strategies**

- **`SignalEquityTrader`**: Loads dynamic `followed_equities.json`; BUY = `USDC_TO_EQUITY`, SELL = `EQUITY_TO_USDC`; no optimistic cooldown mark inside `build_plan`.
- **`USDCopyStrategy`**: Mirrors USDC→WMATIC from followed wallets without marking cooldown until swap success.
- **`evaluate_x_signal_equity_trade`** uses the **same eligibility and sort order** as `try_x_signal_equity_decision` (silent helper for tooling/tests).

## **Key `.env`** (defaults in `.env.example`; production overrides freely)

Examples: `RPC`, `COOLDOWN_MINUTES`, `ENABLE_X_SIGNAL_EQUITY`, `X_SIGNAL_EQUITY_MIN_STRENGTH` **(default template 0.60; tighten in prod if desired)**,
`SWAP_SLIPPAGE_BPS`, `LOG_PREFIX`, Polygon token addresses (`USDC`, `WMATIC`, `ROUTER`).

Load order: `.env` then optional `.env.local` (`override=True`) when present.

## Recent implementation notes (April 2026)

- Unit tests for take-profit paths, swap path candidates, and X-Signal threshold helper (`tests/unit/`).
- No non-core alerting layers in-scope; prioritize strategy code and deterministic logs.

## Today's learnings (1 May 2026)

- POL guard false positive bug.
- `portfolio_history.csv` calculation bug.
- 6-hour cooldown is the biggest bottleneck.
- Only one asset is working due to wrong addresses.
- 6-hour cooldown was never made env-driven (critical mistake).
- `portfolio_history.csv` total calculation bug caused confusion (`~$122` logged vs real wallet `~$102`).
- POL guard produced false-positive skips even when wallet POL was 23+.
- Keep hard risk limits only. Remove artificial profit caps (cooldown, small trade size, low frequency).

## Development workflow

- Local Cursor → tests (`pytest`) → dry-run (`python clean_swap.py --dry-run`; on Windows set `PYTHONIOENCODING=utf-8` if the console rejects emoji prints from legacy modules).
- Windows PowerShell execution-policy-safe pre-commit gate:
  - `powershell -ExecutionPolicy Bypass -File .\scripts\pre_commit_gate.ps1`
  - shortcut: `.\scripts\pre_commit_gate.cmd`
- Coverage tracking (in-repo, periodic):
  - `python scripts/update_coverage_history.py`
  - review `docs/COVERAGE_HISTORY.md` for critical-module trend (ROI-first focus)

## Urgent delta checklist (do not skip)

- Lock a branch matrix before editing:
  - Use generic state toggles and outcomes (for example: feature flag on/off, balance above/below threshold, retry success/fail, signal present/absent).
- For each matrix branch, verify both:
  - control flow (return/continue/skip actually happens)
  - user-facing logs (message reason matches branch cause)
- Add focused unit tests for the matrix above, especially branch behavior and emitted reason strings.
- Never rely on one boolean when multiple block causes exist; store explicit reason text/code and reuse it in skip summaries.
- Prefer explicit enums/reason codes for block states instead of plain booleans when multiple causes can lead to the same skip/block action.
- For future delta requests: keep edits minimal, but first pin a short acceptance checklist and verify each branch in one pass before finalizing.
- After each delta touching guards/logs, run:
  - `python -m compileall -q .`
  - `python -m pytest -q`
- Python note for reviewers: `if/else` blocks do not create local scope. `nonlocal` is required only for assignments inside nested functions/closures.

## One-go execution protocol (required before coding)

- Start every major change request by writing a short acceptance checklist in chat first (expected behavior + logs + test gates).
- Define invariants explicitly before edits:
  - one source of truth per guard
  - fresh-vs-cached state policy per check
  - env/default consistency policy (`.env.example`, code fallback, docs)
- Build/update the branch matrix first, then implement all coupled layers in one pass:
  - decision logic
  - diagnostics/log strings
  - env defaults/template
  - tests
- Add at least one regression test for each non-happy-path branch touched (especially guard-failure and retry-recovery branches).
- Do not close a request until all checklist items are green and logs match the intended branch reason text.

## Release safety gates (required before commit/push)

- Clean tree check:
  - No surprise local edits outside intended delta files.
  - `git diff --name-only` matches expected scope.
- Runtime config consistency:
  - `.env.example` defaults align with code fallbacks and docs.
  - Guard semantics (`gas_ok` vs `ok`) are consistent in touched code paths.
- Verification gate (must pass):
  - `python -m compileall -q .`
  - `python -m pytest -q`
  - Coverage baseline check (periodic): `python -m pytest --cov=. --cov-report=term-missing -q`
  - Coverage history update (periodic): `python scripts/update_coverage_history.py`
- Code quality baseline (as of 2026-05-01):
  - Test coverage: 79% overall
  - clean_swap.py: 58%
  - signal_equity_trader.py: 79%
  - gas_protector.py: 94%
  - swap_executor.py: 60%
  - protection.py: 72%
- Deployment readiness:
  - Do not rely on `git stash -a && pull && stash pop` in VM for normal deploys.
  - Deploy from a clean checkout/branch and restart bot from known commit.
  - Never run two write-enabled bot instances against the same wallet/private key (nonce/conflict risk).

## Security red flags (must warn and stop)

- Never paste or share private keys, seed phrases, or full `.env` contents in chat.
- Never commit `.env` or any credential-bearing file.
- If a request asks to expose secrets (directly or indirectly), agent must refuse and provide a safer alternative.
- Agent should work from `.env.example` + placeholders unless runtime secret access is explicitly required.
- Use separate wallets for stage vs production; rotate keys before moving to production capital.
- Any detected secret-like value in diffs/logs should be treated as a blocker until removed/rotated.

## Operator workflow (for future agents)

- Human operator is the bottleneck; optimize for "deploy once, gather data continuously, iterate in parallel".
- Default mode: keep stage bot running to collect data while code/design iteration continues in Cursor/Grok threads.
- Priority order:
  1) Keep data collection live and stable
  2) Preserve safety/risk limits
  3) Improve PnL with minimal, tested deltas
- If asked for "fastest path", prefer operationally safe one-command flows over broad refactors.

## Tokenized equities (conceptual roadmap)

Replace proxy addresses when Ondo/other issuers publish **Polygon POS** deployments; validate pool depth (`getAmountsOut`) before size-up. Optional later: earnings-calendar-driven filters—not required for baseline execution.

### Parked milestones

- Earnings Volatility Capture Engine v1 (dynamic tokenized equity trading based on earnings calendar + X signals).

## Design rules

- Builder pattern where used; `.env`-driven; risk-first.

**How to continue in any new thread**  
Paste raw: https://raw.githubusercontent.com/krantikaridev/nanoclaw/V2/AI_CONTEXT.md

**Next milestone**  
Earnings Volatility Capture Engine v1, while preserving strict hard risk limits and removing artificial profit caps (cooldown, small trade size, low frequency).

## 🚀 Quick Commands (Nano* Convention Only)

| Command       | What it does                                      | Usage |
|---------------|---------------------------------------------------|-------|
| `nanoup`              | Safe update + restart (recommended)               | `nanoup` |
| `nanomon`             | Quick status + balances + portfolio               | `nanomon` |
| `nanokill`            | Stop the bot                                      | `nanokill` |
| `nanoattach`          | Attach to live bot logs                           | `nanoattach` |
| `sprintmon`           | One-line monitoring (balances + logs + recent trades) | `sprintmon` |
| `auto_usdc_maintain`  | Auto top-up USDC when low for X-Signal equity buys | Uses env `X_SIGNAL_USDC_SAFE_FLOOR` / `X_SIGNAL_AUTO_USDC_TARGET` |

> X-Signal now integrates proactive USDC maintenance in `try_x_signal_equity_decision` when USDC drops below `X_SIGNAL_USDC_SAFE_FLOOR`, targeting `X_SIGNAL_AUTO_USDC_TARGET` before BUY decisions.

### How to stop/restart the bot

### How to stop/restart the bot
```bash
nanokill
nanoup