# Nanoclaw v2 - AI Context (Single Source of Truth)

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

Load order: `.env` then `.env.local` (`override=True`).

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
