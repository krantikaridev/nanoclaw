# Nanoclaw v2 - AI Context (Single Source of Truth)

**Canonical governance**: All process steps, backlog items, handoff rules, and session hygiene for this repo are defined **here first**. Cross-link from README or chat, but avoid duplicating TODO lists elsewhere—update this file.

## **AI / Cursor convention (Aniki)**

- **Aniki**: Operator shorthand for the default **Cursor (or Grok) coding agent** on this repo—use in threads, commits notes, and handoffs so humans and agents share one label.
- **“What the bot said”** means output from **`real_cron.log`**, **`nanostatus`**, **`nanopnl`**, and **`nanodaily`**—it reflects **coded** balance math and parsers, **not** custody UI (MetaMask) or full wallet taxonomy by default. **Capital decisions** should cross-check **Polygonscan** (see **On-chain ground truth**).
- **Every new agent thread** (Cursor / Grok / etc.): do **not** rely on in-chat memory alone—pull or paste the sections listed in **New Thread Protocol**. When **`TOTAL`** or **`STABLE_USD`** disagreed with MetaMask, record **both numbers + date/time (UTC)** in commit messages, **`agent_feedback/`**, or PR notes under the label **“what the bot said”** so the record shows the divergence explicitly.

## **On-chain ground truth (no screenshot required)**

- **Authoritative public state** for the bot wallet is **Polygon PoS** at **`https://polygonscan.com/address/<WALLET>`** where **`<WALLET>` must exactly match `WALLET=` in runtime `.env`** (also in `.env.example` as the stage template). If the URL address and **`WALLET=`** differ, fix the URL or env before reconciling PnL—reconciling against **another** address (e.g. an old paste) guarantees a false PnL story.
- **Historical “~\$103 two days ago”** when no screenshot exists: there is **no** archived “single ground-truth frame” unless you **define** it. Reconstruct deliberately: pick the **UTC date/time** of the observation, then label the **source**—**MetaMask** total (which network tab?), **Polygonscan** token-holdings / exports for **`WALLET=`**, an **`old nanopnl` / `real_cron.log` `WALLET TOTAL USD` line**, or **`portfolio_history.csv`**. Those four **often diverge** (dual USDC, WETH/POSI not in bot **`TOTAL`**, RPC failures, oracle marks); do **not** treat them as interchangeable without naming which one you mean.
- **Polygonscan** for the canonical wallet is the best **public** anchor for **token quantities**; USD at a past instant still depends on oracles/UI. Use **Transactions** + optional **CSV export** + dated log lines for the same window.
- **MetaMask “total” vs bot `TOTAL`**: The bot is **Polygon PoS–only** (chain **137**). MetaMask can aggregate **Ethereum, Polygon, and other networks**. **WETH on Ethereum** uses contract **`0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2`**; **WETH on Polygon** (what `followed_equities` / `FE_USD` quote) uses **`0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619`**. Holdings on Ethereum **do not** appear in **`FE_USD`** or **`WALLET TOTAL USD`**—reconcile MetaMask per **network** (Polygon tab only) vs **`WALLET=`** on Polygonscan.
- **MetaMask “All popular networks”** can aggregate **multiple chains and hidden tokens**; **`nanopnl` TOTAL** is **intentionally narrower** until **v2.9** expands “full wallet mark-to-market” (see **What the bot reports vs UI**).

## **Stage policy — one wallet, what “PnL” means**

- **Canonical custody**: **One Polygon `WALLET=`** is the stage/production trading wallet unless you explicitly rotate keys and update **`.env`** everywhere.
- **v2.8 benchmark (today’s bar)**: **Headline success** = **RPC green (`nanohealth`)**, **stablecoin bucket** (`STABLE_USD` / both USDC variants + USDT) reconciles to **Polygonscan** for that wallet, **`nanopnl --reset-session`** anchored once—session % is meaningful **relative to that baseline**, even if MetaMask **all-network** headline ≠ bot **`TOTAL`**.
- **v2.8.0 release scope — Polygon-only accounting**: Tag **v2.8.0** when the **Polygon** picture is credible (stables + **`WALLET TOTAL USD`** vs **Polygonscan** for **`WALLET=`** on chain **137**). **`FE_USD` / followed-equities** apply to **Polygon** tokens only (e.g. Polygon WETH `0x7ceB…`). **Ethereum or other networks** (e.g. mainnet WETH `0xC02a…`) are **explicitly out of scope** for v2.8 PnL—do **not** pause Polygon trading solely because off-Polygon assets exist; they simply do not enter **`TOTAL`** until multi-chain support. Operators who need one “whole wallet” number must **reconcile the Polygon tab only** to the bot, **bridge** material balances to Polygon so they count in-bot, and/or **book off-Polygon manually** until the multi-chain backlog ships.
- **v2.9+ (full picture, MetaMask-parity direction)**: **Operator intent** is to model **as much of the wallet as practical**—extend **`followed_equities` / quoting**, add an **inventory / MTM series**, or an explicit **`unmodeled USD`** bucket so reports do not silently ignore **WETH / POSI / dust**. Until then, **`TOTAL`** is **not** promised to match MetaMask’s headline.

## **What the bot reports vs MetaMask / Polygonscan**

| Source | What it is |
|--------|------------|
| **`STABLE_USD` / USDT / USDC** in logs | **USDT** + **USDC.e + native USDC** (`USDC` + `USDC_NATIVE` in `.env`), from **`balanceOf`**. Should be close to MetaMask’s two USDC lines summed. |
| **WMATIC** in logs | **Token quantity**, not USD; USD in TOTAL uses **`get_live_wmatic_price()`** (can differ slightly from MetaMask’s mark). |
| **`FE_USD`** | **USDT-notional** for **non-core** rows in **`followed_equities.json`** (e.g. **Polygon WETH** `0x7ceB…`)—same `balanceOf` on **Polygon** as stables. **Not** Ethereum-mainnet WETH (`0xC02a…`); MetaMask totals often mix chains. Uses **V2 router**, **QuoterV2**, multihop; optional **`current_price_usd × balance`**. **`FE_USD=$0`** with “WETH” in MetaMask: confirm you’re on **Polygon** token details (contract **`0x7ceB…`**) or expect **zero** on-chain for that asset on Polygon; look for **`BALANCE READ FAILED`** if reads error. **Silent zero-quote diagnostic (May 2026)**: when `bal>0` but every quote tier returns 0, `runtime._followed_equity_tokens_usdt_usd` emits `[nanoclaw] FE_USD UNQUOTED \| sym=… \| bal=… \| fallback_px_usd=… \| contributed_to_total=$…` to `real_cron.log`. **Fallback floor semantics (Cleanup #3, May 2026)**: `current_price_usd` is a **true floor**. Effective per-asset USD = `max(live_quote_usdt, bal × current_price_usd)`. Pre-cleanup, live always won when `> 0`, so a degraded pool / large-size impact (LINK_ALPHA at $35.78 vs spot $53.52 on 2026-05-26) silently undercount `TOTAL`. When fallback wins, an operator diagnostic `FE_USD FALLBACK FLOOR APPLIED \| sym=… \| live_quote_usdt=… \| fallback_total_usd=… \| contributed_to_total=…` is logged so the gap against MetaMask is visible at the moment it happens. Populated for `WETH_ALPHA` / `WBTC_ALPHA` / `LINK_ALPHA`. **Operators MUST refresh `current_price_usd` periodically** — a stale fallback above true spot will overstate `TOTAL`. |
| **`TOTAL` (runtime)** | **USDT + USDC (both) + WMATIC×price + POL×`POL_USD_PRICE` + `FE_USD`**. Read via the canonical helper **`modules.runtime.compute_authoritative_total_usd(balances)`** (Cleanup #1, May 2026): the `WALLET TOTAL USD` log line, `portfolio_history.csv::total_value`, and `scripts/pnl_report.py` (in-process via `compute_authoritative_total_in_process`) all funnel through this one function so the four touchpoints cannot drift. The regex `AUTHORITATIVE_TOTAL_PATTERN_V2` in `pnl_report.py` is now a read-only fallback for parsing historical `real_cron.log` rows when in-process RPC is unavailable. Not guaranteed to equal MetaMask’s all-network headline. |

## **Operating Model (roles + loop)**

- Canonical role split and collaboration loop live in `docs/OPERATING_MODEL.md`.
- Keep this file as canonical backlog/process memory; keep role mechanics in the operating-model doc to avoid drift.

## **Developer environments (shell + machine)**

- **Local / Cursor**: Often **Windows + PowerShell** — do not assume **`&&`** (use **`;`** / **`$LASTEXITCODE`** on PS 5.x, or **PowerShell 7+**). See **`docs/DEV_WORKFLOW.md`** § *Shell: Windows vs Linux*.
- **Stage VM**: **Ubuntu + bash** — `nanoup`, `grep`, and **`docs/readme-vm-update.md`** snippets are written for **POSIX**. Optional **External Risk Layer**: **`./start_external.sh`** (or **`python external_layer/control.py`**) refreshes repo-root **`control.json`** ~every 30s; **`nanoclaw`** reads it each cycle—tier/clamp thresholds via **`EXTERNAL_RISK_*`** / **`EXTERNAL_CLAMP_*`** in **`.env`** (`external_layer/clamp_policy.py`)—details in **`external_layer/README.md`**.
- **Agents**: When giving copy/paste commands, **name the environment** or provide both forms so instructions match where they run.

## **Systematic Learning & History**

- Hard cap $4.50 on high-conviction size + 600 bps fallback.
- **\$424.63 portfolio peak on 2026-05-01** reflected **test-mode / dummy instrumentation**, not verified on-chain wealth. Confirm any “peak” narrative against Polygonscan wallet history and live balances—**there was no real on-chain balance matching that headline figure**.
- **Bleed-rate target**: **\$0/day** sustained drawdown from noise, gas bleed, or misconfigured paths—optimize for stability before increasing size.
- **Profit-taking policy**: **`TAKE_PROFIT_PCT` lowered to 5%** effective **2026-05-02** (baseline take-profit tier; tune only with logged evidence).
- **`portfolio_history.csv` hygiene**: Rows must not imply execution that never happened—**purge test-mode eras** using `scripts/clean_dummy_data.sh` (swap-correlated filtering via `real_cron.log`; see script docstring). **portfolio_history CSV last cleaned (automated)**: 2026-05-02 (UTC)
- Operational rule: Prefer **fewer misleading charts** over **dense but false** telemetry.

## **New Thread Protocol** (Grok / agent handoff)

When a Grok (or Cursor) thread hits the message limit—or you deliberately start fresh—avoid losing operational truth.

1. **Open the canonical snapshot**: Fetch raw `AI_CONTEXT.md` from branch `V2`: `https://raw.githubusercontent.com/krantikaridev/nanoclaw/V2/AI_CONTEXT.md`
2. **Paste the operative sections** into the new thread **or** the first message: minimum = **AI / Cursor convention (Aniki)**, **On-chain ground truth**, **What the bot reports vs UI**, **Systematic Learning & History**, **Strategic release train (big picture)**, **Current Situation**, **TODO & Backlog**, **House-Cleaning Checklist**, and **V2.5.11+ Roadmap**, plus wallet (public) context if rotating.
3. **Follow the detailed checklist**: Step-by-step copy/paste order and pitfalls live in **`docs/NEW_THREAD_PROTOCOL.md`**.
4. **Declare branch + scope** in thread #1 (`V2`, stage vs prod, VM vs local).
5. **Secrets**: Never paste `.env`; refer only to **`.env.example` keys by name.**
6. **First action in-thread**: Align on acceptance criteria once, then execute—mirror **One-go execution protocol** below.

## **House-Cleaning Checklist** (end of every substantive session)

- [ ] **`git status` / `git diff --name-only`** — scope matches intention; no surprise files.
- [ ] **`python -m compileall -q .`** and **`python -m pytest -q`** after code changes (or **`scripts/pre_commit_gate.ps1`** / **`scripts/pre_commit_gate.sh`**).
- [ ] **Dev workflow** — follow **`docs/DEV_WORKFLOW.md`** (commit gate, `.env` hygiene, `nanoenv_example.py`, `nanoup.sh`) and **`docs/readme-vm-update.md`** for reusable VM deploy/release flow.
- [ ] **Commit** with a factual message (what / why).
- [ ] **Update `AI_CONTEXT.md`** — backlog, dates, incidents, roadmap (this file stays current).
- [ ] **CSV sanity** — if anything looked like test-mode spikes, run **`scripts/clean_dummy_data.sh`** after backup approval; reconcile with Polygonscan.
- [ ] **`nanohealth`**, then **`nanostatus` / `nanopnl`** — RPC gate first; then spot-check totals vs on-chain intuition after deploy.
- [ ] **Optional artifact bundle** — `./scripts/package_runtime_artifacts.sh` before sharing externally.
- [ ] **Parked ops** — `bash scripts/nanobot_aliases.sh --install` + `source ~/.bashrc` on VM once so **`nanohealth`** is on `PATH` (until then: `python scripts/nanohealth.py`).
- [ ] **Reminder**: no two write-enabled bots on one wallet key.

## **v2.8.0 PnL benchmark — same-day closure (operator)**

Use when tagging **v2.8.0** after stage is RPC-green and accounting is understood (even if MetaMask headline ≠ bot TOTAL—document **Why** using **What the bot reports vs UI**).

**Razor focus (operator)**: Treat **v2.8 PnL benchmark closure** as the blockers for the tag—not feature churn. Same calendar day in IST is an explicit target when you say “must go today”; anything else is **parked** to **v2.9** unless it is RPC, stable reconcile, or **tag hygiene**.

- [ ] **`nanohealth`** (or `python scripts/nanohealth.py`) **ok** (`chain_id=137`).
- [ ] Recent **`WALLET TOTAL USD`** lines show **`STABLE_USD=`**; stables reconcile with Polygonscan token tab for **`WALLET=`** (both USDC contracts + USDT).
- [ ] **`nanopnl --reset-session`** done once after trusting balances—session % anchored to that instant.
- [ ] **`nanodaily`** (or `python scripts/pnl_report.py --daily-summary`) shows **📅 LOOKBACK** — past **`total_value`** from **`portfolio_history.csv`** at each horizon (default **24h** if you omit `--lookback`; **`nanodaily`** passes **1h … ~1m**). **n/a** until the CSV has a row **at or before** that time — needs the bot to have run and appended snapshots. **Wallet top-ups / withdrawals** appear as **step changes** in that series (same as your gold-chart mental model); separating **performance vs flows** is a **v3.0+** accounting item, not a v2.8.0 tag blocker.
- [ ] **`git log -1 --oneline`** on VM matches commit you tag locally; **`git tag -a v2.8.0`** + **`git push origin v2.8.0`** when satisfied.

## **Venue scope (India, Polymarket, equities) — not legal advice**

- **Nanoclaw `V2`** scope today: **Polygon PoS on-chain** execution and telemetry in this repo. Prove **reliable PnL here** before adding venues.
- **India**: Automated trading in **Indian retail equities/derivatives** is **heavily regulated** (SEBI, broker APIs, retail algo rules). Treat any India expansion as **separate product + compliance review**—not a quick env toggle.
- **Polymarket / prediction / CEX**: **Geo, KYC, and availability** vary; often **not** drop-in for the current `swap_executor` path. Defer to **v3+** with explicit jurisdictional sign-off.
- **\$100k big-picture**: sequencing is **credible stage PnL → production ramp (v3.0.0) → scale (v4)** per **Strategic release train**—venue diversification only **after** accounting and risk gates hold.
- **Pragmatic next bets**: Getting **one chain + one wallet** to a **provable** daily PnL beats spreading capital across **Polymarket**, **Indian cash equities**, or **discretionary bots** before you trust the numbers here—those venues need **compliance and product** work, not a hurried env flag.

## **V2.5.11+ Roadmap**

| Tier | Track | Items |
|------|-------|-------|
| **High ROI** | Risk & monetization | 5% take-profit tier (**active policy 2026-05-02**); **dynamic valuation baseline** (seed vs accrued growth); **per-trade / per-cycle PnL attribution** wired to exits and gas; **`portfolio_history`/telemetry never diverges from chain reality** |
| **High ROI** | Execution | **Option C** routing / aggregator path tuning once gas normalizes; **cooldown lattice** tuning (global vs per-asset) with empirical cycle data |
| **Medium ROI** | Quality | **Modular bot core (V2)**: `clean_swap.py` is a thin façade; logic lives in `modules/runtime.py` (env, balances, TP, state), `modules/signal.py` (X-signal equity), `modules/swap_executor.py` (precedence + `main`), `modules/attribution.py` (trade/tx logging hooks), `modules/agent_layer.py` (optional Grok + Telegram). Monolith reference: git history. **Automated CSV clean** maturity (broader matchers if log format evolves); tighten **Pylance** / typing on façade + modules; incremental **coverage** (see `tests/` and GitHub Actions `ci.yml`) |
| **Medium ROI** | Platform | Smoke **Docker**/`deploy_vm_safe.sh` parity after risky merges |

Parking lot: earnings-volatility engine (see roadmap below), **see also DB Migration Discussion.**

## **DB Migration Discussion** (future)

A prior thread noted **`portfolio_history.csv` as a transitional store** — acceptable for stage telemetry, brittle for auditing at scale (**concurrency**, **schema versioning**, joins with swap receipts). No migration is committed on `V2` yet. When ROI validation passes, evaluate a **minimal append-only persistence layer** (e.g., SQLite single-file initially) keyed by `(tx_hash, timestamp)` before introducing operational complexity.

---

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
**Wallet**: 0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6

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

Default: Protection → Profit take (`evaluate_take_profit`) → **X-Signal equities** (`try_x_signal_equity_decision`) → USDC copy → polycopy/target wallets → main USDT↔WMATIC logic.

**Signal-Driven Rotation (May 2026):** When a **rotation-priority X-Signal BUY** is present (`rotation_priority_detector()`), precedence shifts to **Protection → X-Signal → Profit take → …** so high-conviction external intelligence rotates capital before WMATIC profit-taking. Main-strategy **USDT→WMATIC** accumulation is deferred in the “hold” band when rotation priority is active; P2 small WMATIC→stable relief is also deferred so the cycle can execute the X-Signal plan first. **`strong_buy_detector()`** is unchanged (AUTO-USDC “strong buy”, `X_SIGNAL_STRONG_THRESHOLD` plan bar). **`X_SIGNAL_ROTATION_PRIORITY_THRESHOLD`** defaults to the strong threshold — lower it (e.g. `0.78`) to widen precedence without changing strong-buy / sizing logic. Optional: `X_SIGNAL_ROTATION_MIN_UPSIDE_PCT` lets force-eligible BUYs trigger rotation on upside alone. Goal: faster, hours-to-2-day rotation driven by X signals instead of long WMATIC-centric accumulation.

Operational focus: USDC liquidity for equity **buys**, conviction-tier plan ordering, and execution on Polygon **chain ID 137** only.

## Execution & observability

- **`followed_equities.json`**: `min_signal_strength` in JSON and `X_SIGNAL_EQUITY_MIN_STRENGTH` in env both apply — **effective floor = max(JSON, env)**. Logged each X-Signal check as `[nanoclaw] X-Signal threshold …`.
- **Polygon test proxies**: current repo config uses Polygon-native staples (WMATIC / WETH / WBTC) plus `_note` where Ondo tickers remain off-chain-Polygon until official listings; replace `address` when real Polygon contracts exist.
- **Logs**: `[nanoclaw]` prefix via env `LOG_PREFIX`; cycle banner; path tags (`🔍 DECISION PATH`). X-Signal emits threshold line, ACTIVE lines, SUMMARY line, and (when a plan exists) checksum `token_in` / `token_out` before swap.
- **Decision logging (learning/adaptation foundation — May 2026)**: `modules/decision_log.py` emits grep-friendly pipe lines for post-hoc analysis and persists basic counters in `bot_state.json` → `decision_tracking`:
  - **Standard line**: `[nanoclaw] DECISION | branch=X_SIGNAL|PROFIT_TAKE|MAIN_STRATEGY | action=ACCEPT|REJECT|TAKE|HOLD|DEFER|EXECUTE | reason=<code> | symbol=… | signal=… | edge_pct=… | notional_usd=… | wmatic=… | extra=…`
  - **X-SIGNAL alias** (backward compatible): `X-SIGNAL DECISION | symbol=… | action=… | reason=…`
  - **Counters**: `X_SIGNAL.taken` / `skipped` (per-symbol plan accept/reject), `X_SIGNAL.cycle_taken` / `cycle_skipped` (branch outcome per cycle); `PROFIT_TAKE.hold` / `take_signal` / `deferred` / `executed_attempts` / `executed_success` (success rate = success÷attempts); `MAIN_STRATEGY.profit_exit_planned` (WMATIC→stable exits from main band logic).
  - **Rollup**: end of `determine_trade_decision` prints `[nanoclaw] DECISION_TRACKING | …` — parse `real_cron.log` or read `bot_state.json` for dashboards; intended for future threshold tuning, not operator alerts.
- **Balance logger**: integrated into `clean_swap.py` (`Source=BotLogger`) reading `balance_config.txt` every 600s; no separate `scripts/auto_balance_logger.sh` process needed.
- **Balance logger guardrail**: skips writing snapshots when `balance_config.txt` is missing/empty/invalid to avoid zero-value noise in `real_cron.log`.
- **Fluctuation protection**: `FLUCTUATION` now emits rich trigger context, honors `PROTECTION_FLUCTUATION_COOLDOWN_SECONDS` to suppress repeated force-sell triggers in short windows, and applies `PROTECTION_FLUCTUATION_MIN_SELL_USD` to ignore low-notional noise triggers. Force-sell is **skipped** when **USDT+USDC** (both USDC contracts) is still **≥ `FLUCTUATION_HEALTHY_TOTAL_STABLES_USD`** (~$77.5) even if USDT alone is below `PROTECTION_FLUCTUATION_USDT_THRESHOLD`.
- **Cooldowns**: per-asset and per-wallet marks run **after a successful on-chain swap** (`approve_and_swap` returns tx hash), not when a plan is merely built (`SignalEquityTrader.build_plan`, `USDCopyStrategy.build_plan`).
- **Global cooldown**: skips full cycle until `COOLDOWN_MINUTES` since `last_run`; log prints approximate seconds remaining.

## **`swap_executor.approve_and_swap`**

- Rejects **`token_in == token_out`** (misconfiguration / wrong `USDC` env).
- **`getAmountsOut`** quote on Router with combined ABI (`ROUTER_SWAP_AND_QUOTE_ABI`); tries **direct** path first, then **WMATIC hop**, then **USDC hop** between non-endpoint intermediates (`build_polygon_swap_path_candidates`).
- **`swapExactTokensForTokens`** uses **`amount_out_min`** from quoted output × `(1 - SWAP_SLIPPAGE_BPS/10000)` (default slippage 1%; env `SWAP_SLIPPAGE_BPS`). Longer paths use higher gas limits.
- **Router fallback (when 1inch is missing or errors, e.g. HTTP 403):** logs **`[FALLBACK ROUTER]`** plus clearer 1inch error typing (HTTP vs URL). Fallback quoting uses **looser slippage** than `SWAP_SLIPPAGE_BPS` by default (`max(base+150 bps, 250 bps)`, overridable via `FALLBACK_ROUTER_SLIPPAGE_BPS`). **One on-chain retry** after a revert uses **`+ONCHAIN_SWAP_RETRY_EXTRA_BPS`** (default **50** = +0.5%) over the first fallback slippage, with log `RETRY ATTEMPT 1/1 | Increasing slippage to … bps` (override absolute second tier via `FALLBACK_ROUTER_RETRY_SLIPPAGE_BPS`). **1inch path:** same single retry with refreshed quote at **`SWAP_SLIPPAGE_BPS + ONCHAIN_SWAP_RETRY_EXTRA_BPS`** if the first swap reverts on-chain.
- **Directions** without explicit tokens: backward-compatible resolutions for USDT/WPOL paths; equity directions supply `token_in` / `token_out` from plans.

## **Strategies**

- **`SignalEquityTrader`**: Loads dynamic `followed_equities.json`; BUY = `USDC_TO_EQUITY`, SELL = `EQUITY_TO_USDC`; no optimistic cooldown mark inside `build_plan`.
- **`USDCopyStrategy`**: Mirrors USDC→WMATIC from followed wallets without marking cooldown until swap success.
- **`evaluate_x_signal_equity_trade`** uses the **same eligibility and sort order** as `try_x_signal_equity_decision` (silent helper for tooling/tests).

## Signal-Driven Rotation & temporary safeguards (May 2026)

Directional shift: reduce WMATIC-centric main-strategy dominance; prioritize **external X-Signal** capital rotation (shorter holds, opportunistic entries).

- **X-SIGNAL blocked symbols** (`modules/signal.py`): repo-root (or cwd / `followed_equities.json` dir) file **`.xsignal_blocked_symbols`** — one symbol per line (e.g. `WMATIC_ALPHA`, `WETH_ALPHA`). Loaded at cycle start (mtime-cached). Blocked symbols are dropped **before** eligibility, gas pre-flight, and `build_plan` in `try_x_signal_equity_decision` / `evaluate_x_signal_equity_trade`; execution paths re-check via `_x_signal_apply_blocked_symbol_filter` in `modules/swap_executor.py`. Missing file → no blocks (graceful). If the block list would remove **all** followed assets, blocks are **ignored for that cycle** with a WARNING. Optional env skip list: **`X_SIGNAL_TEMP_SKIP_SYMBOLS`** (default empty). Template: **`.xsignal_blocked_symbols.example`**. Log: `[X-SIGNAL] Skipping blocked symbol: SYM (from .xsignal_blocked_symbols)`.
- **WBTC liquidity min notional (TEMPORARY — May 2026)** (`signal_equity_trader.build_plan_with_block_reason`): symbols containing **`WBTC`** require BUY notional ≥ **`X_SIGNAL_WBTC_MIN_NOTIONAL_USD`** (default **$10** — lowered from $25 in May 2026 after observing it blocked WBTC_ALPHA 100% on small bankrolls where typical X-SIGNAL sizing is ~$10.25; the realized-slippage ceiling on the small-tier execution path is the actual fill safety net at this notional). **Not** bypassed by high-conviction size/effective overrides. Set **`X_SIGNAL_WBTC_MIN_NOTIONAL_USD=0`** to disable; raise back to $25+ if a specific window's WBTC liquidity degrades. Does not affect LINK_ALPHA or other assets.
- **USDC fragmentation guard (May 2026)** (`signal_equity_trader.build_plan_with_block_reason`): the swap layer can only spend from **one** ERC20 contract, but eligibility/sizing treats bridged **USDC.e** + **native USDC** as a single combined budget. After a successful on-chain read, `_query_onchain_usdc_balance` records **per-variant balances** in `_last_known_per_variant_usdc_balances`; `_max_per_variant_usdc_balance_usd()` returns the best single-variant balance. If `trade_size > max_per_variant`, size is capped to `max_per_variant * (1 - X_SIGNAL_PER_VARIANT_USDC_EPS_BPS/10000)` (default **50 bps**); when the cap drops below the swap-executor's effective floor `max(min_trade_usdc, MIN_TRADE_USD)` the BUY is rejected with reason **`insufficient_per_variant_usdc`**. The plan-time check mirrors `_x_signal_min_trade_guard_bypass` so high-conviction trades (`|signal| ≥ 0.85` and `capped ≥ _X_SIGNAL_MIN_SIZE_OVERRIDE` ≈ $7.5) still proceed when the executor would have allowed them. RPC fallback paths leave the cache empty so the cap fails open (no false skips). Logs: `[nanoclaw] X-SIGNAL trade size capped (USDC fragmentation) | …` (cap applied) or `[nanoclaw] X-SIGNAL skipped | insufficient per-variant USDC | …` (rejected — actionable; tells operator to consolidate USDC variants instead of leaking through to the executor's generic `min_trade_guard` log). Without this guard, the SwapRouter reverts `STF` on `USDC.transferFrom` when the requested amount exceeds the spendable variant balance.
- **Minimum net-edge filter (v1, active — conservative defaults May 2026)** (`modules/swap_executor.py`): Foundation gate to avoid repeated low-quality entry churn after gas/fees. **USDC→equity** (X-Signal) and **USDT→WMATIC** (main strategy) must show estimated **net** edge ≥ **`MIN_NET_EDGE_PCT`** (env, default **2.0%**; module `_MIN_NET_EDGE_PCT`) after **`MIN_NET_EDGE_FEE_BUFFER_PCT`** (default **0.75%** swap fee/slippage reserve) and rough gas (`effective gross − gas`, as % of notional). **Gross planning**: X-SIGNAL uses `plan_x_signal_gross_edge_pct(signal, upside_pct)` — linear in `|signal|` from the 0.6 eligibility floor (no 3% gross cushion for weak signals); stored on `TradeDecision.expected_gross_edge_pct` in `modules/signal.py`. Main BUY uses **`MAIN_STRATEGY_ENTRY_EDGE_FRAC` × `TAKE_PROFIT_PCT`** (default **0.70**) unless **`MAIN_STRATEGY_ENTRY_EDGE_PCT` > 0**. **Fail-closed** when notional is missing/zero. **Early gates** (before execution): `try_x_signal_equity_decision` (`stage=x_signal_plan`), `select_main_strategy_trade` (`main_strategy_plan`), then `determine_trade_decision` (`x_signal_decision` / `main_strategy_decision` / stable-rotation fallback) — all **before** dust defer; **`main()`** re-checks with live gas before `approve_and_swap`. Planning gas: **`NET_EDGE_PLANNING_GAS_GWEI`** (default **120** gwei). Exits and copy paths unchanged. Once per process: `[nanoclaw] MIN_NET_EDGE_ACTIVE | threshold=…% net after gas | fee_buffer=…% | planning_gas=…gwei | directions=…`. Rejection: `[nanoclaw] LOW EDGE REJECTED | expected_net=…% | notional=$… | floor=…% | …`. Structured: `decision_log` **REJECT** / `below_min_net_edge`. Tune **`MIN_NET_EDGE_PCT`** down only with logged fill/PnL evidence.
- **X-SIGNAL dynamic minimum effective size** (`nanoclaw/strategies/signal_equity_trader.py`): env tiers **`X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_BASE`** (default **$12**, `|signal| ≥ 0.85`); **`X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_MEDIUM_TIER`** (**$14**, `≥ 0.80`); **`X_SIGNAL_MIN_EFFECTIVE_TRADE_USD_WEAK_TIER`** (**$15**). When **USDC < `X_SIGNAL_USDC_SAFE_FLOOR`**, gate caps at **`X_SIGNAL_LIMITED_USDC_MIN_EFFECTIVE_GATE_USD`** (default **$10**). **PnL recovery cap** (`X_SIGNAL_RECOVERY_*`): lowers gate to **`X_SIGNAL_RECOVERY_MIN_EFFECTIVE_GATE_USD`** (default **$9**) when **any of**: **`MAIN_STRATEGY_PNL_RECOVERY_MODE`** or **`PNL_RECOVERY_MODE`**; **`control.json`** `stable_usd < X_SIGNAL_RECOVERY_STABLE_USD_MAX`; `max_copy_trade_pct ≤ X_SIGNAL_RECOVERY_MAX_COPY_PCT_THRESHOLD` (default **0.06**); session PnL negative. Recovery also **lifts notional** by **`X_SIGNAL_RECOVERY_GAS_BUFFER_USD`** (default **$1.25**) so effective after gas clears the cap. **Execution:** recovery `|signal| ≥ 0.80` at ≤$12 notional uses **small** high-conviction fallback (8000/10000 bps, looser min_out) instead of gated tier — fewer on-chain reverts. High-conviction bypass allows **$7** effective when `|signal| ≥ 0.85`, or **`≥ 0.80`** under limited USDC or recovery gate.
- **X-SIGNAL plan ordering** (`modules/signal.py`): eligible assets sorted by cooldown-ready → conviction tier → **quality score** (`|signal|`, optional `track_record_score` / `upside_pct` in JSON) → `|signal|`; winner prefers force-eligible / high-conviction **BUY** plans. Optional noise filter: `X_SIGNAL_MIN_ACTIONABLE_STRENGTH`, `X_SIGNAL_MIN_UPSIDE_PCT_FOR_WEAK` (0 = off). Structured logs via `decision_log.log_x_signal_decision` (fields: signal, edge_pct, notional_usd, wmatic, reason); legacy alias `X-SIGNAL DECISION | …` retained.
- **Dynamic USDC sizing** (`signal_equity_trader._x_signal_dynamic_lo_hi`): uses `X_SIGNAL_DYNAMIC_*` env (USDC tier caps/boosts before signal interpolation).
- **Precedence override** (`modules/swap_executor.py`): `rotation_priority_detector()` → X-Signal before profit-take; P2 relief and main USDT→WMATIC buy deferred when rotation is active.
- **X-SIGNAL execution quality** (Signal-driven — May 2026; **CRITICAL for rotation PnL**): without reliable on-chain fills, signal-driven rotation burns gas and never moves capital. **Every** USDC→equity X-SIGNAL BUY uses enhanced fallback execution via `modules/swap_executor._resolve_x_signal_enhanced_fallback_execution` (tiers: **small** ≤$12 & `|signal|≥X_SIGNAL_SMALL_GATED_MIN_STRENGTH` (default **0.80**) → `X_SIGNAL_SMALL_HIGH_CONVICTION_*` **3000/5000** bps (tightened from 8000/10000 in May 2026 — V3 pre-flight `check=ok` validates the quote and fills at 8000 bps showed realized slippage well under the ceiling, so the new value cuts worst-case loss-per-trade ~$8→~$3 with 5× safety margin over typical fills); **gated** when notional ≥ dynamic gate and small tier does not apply → `X_SIGNAL_GATED_TRADE_*` **9500/12500** bps; **default** → `X_SIGNAL_DEFAULT_*` **7000/11000** bps). **Conservative first step:** `|signal|≥0.90` lowers tier **primary** by **`X_SIGNAL_HIGH_CONVICTION_PRIMARY_RELIEF_BPS`** (default **800**); slippage **ramp** still reaches retry bps. Tiered `min_out` buffer: gated base **100** bps + high-conviction add-on (`|signal|≥0.90` full `X_SIGNAL_HIGH_CONVICTION_MIN_OUT_EXTRA_BPS`, **≥0.85** half); small tier **50** bps base. **`swap_executor.approve_and_swap`**: pre-flight quote **failure or sanity reject** for X-SIGNAL **defers to slippage ramp** (does not abort before retry); ramp quote failures **continue** to next step; structured `_log_x_signal_quote_failure` diagnostics (per-fee errors when available). **Quoting stack:** per fee tier **QuoterV2 → QuoterV1** (`X_SIGNAL_QUOTE_PREFER_QUOTER_V2`); small trades probe **3000→500→10000** first (`X_SIGNAL_SMALL_TRADE_USDC_RAW`, default **15M** raw USDC); when all V3 single-hop pools fail → **V2 router** multihop quote+swap (`X_SIGNAL_V2_ROUTER_FALLBACK_ENABLED`). Ramps slippage in up to **four** steps when primary→retry gap ≥ **2000** bps (`_x_signal_fallback_slippage_ramp`), re-quotes after **`X_SIGNAL_FALLBACK_REQUOTE_DELAY_SECONDS`** (default **1.5s**), **pre-flight** before submit (quote sanity, max age **`X_SIGNAL_PREFLIGHT_MAX_QUOTE_AGE_SECONDS`** default **8s**, stale → re-quote; **`eth_estimateGas`** cap **`X_SIGNAL_PREFLIGHT_MAX_GAS_LIMIT`** default **650k**), **stable preference** for the **3000** pool when within **`X_SIGNAL_STABLE_FEE_PREFER_BPS`** (default **75**) of the best V3 quote. **STF backoff:** each STF revert → short per-asset cooldown (`X_SIGNAL_STF_FAILURE_COOLDOWN_SECONDS`, default **600s**); after **`X_SIGNAL_STF_PAUSE_AFTER_FAILURES`** (default **2**) → long pause (`X_SIGNAL_STF_PAUSE_SECONDS`, default **3600s**, escalates × **`X_SIGNAL_STF_PAUSE_ESCALATION_MULTIPLIER`** per repeat cycle, cap **`X_SIGNAL_STF_MAX_PAUSE_SECONDS`**); state `x_signal_stf_backoff` (`pause_generations`); STF-paused symbols sort **last** with tiered penalty in `modules/signal` plan pick. Logs: `[nanoclaw] X-SIGNAL execution quality | EXEC ATTEMPT|SUCCESS|FAILED` (includes `notional`, `signal`, `slippage_bps`, `min_out`, `fee_tier`, `amount_in`, `revert`); router `[FALLBACK ROUTER] X-SIGNAL slippage ramp|re-quote delay|min_out buffer|pre-flight quote|quote failed|quote retry|mode=v2`; plan `[nanoclaw-av] X-SIGNAL gated trade eligible — enhanced execution on swap` (plan-time; execution tier may be **small** even when gated at plan build).

- **P2 Profit-Take Relief** (TEMPORARY SPRINT FIX — May 2026; revert after sprint window):
  - `_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_WMATIC_USD_MIN = 7.0` — total WMATIC stack must be ≥ ~$7 USD equiv (trade notional may still be small).
  - `_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_NOTIONAL_FLOOR_USD = 8.0` — P2 relief notional floor (May 2026; raised from $2.0 → $5.0 → **$8.0**) to block sub-$8 micro exits that burn gas on healthy stacks.
  - `_MAIN_STRATEGY_PROFIT_TAKE_BALANCE_RELIEF_MIN_SIGNAL_STRENGTH = 0.55` — bypass gate; `_profit_take_balance_relief_signal_strength()` prefers `profit_signal['signal_strength']`, else sprint heuristics. When WMATIC ≥ $7 and exit reason is not HOLD, strength is never below **0.55**. HOLD snapshots are ignored for scoring when the stack is healthy (stops `main_strategy_dust_deferred` on rotation sells). Strengths rounded to two decimals.
  - Allows small WMATIC → USDT/USDC profit takes below `MIN_TRADE_USD` when stack + notional + signal pass; skips `min_trade_guard` in `main()` when bypass qualifies.
  - **Precedence:** for `WMATIC_TO_USDT` / `WMATIC_TO_USDC`, `_profit_take_balance_relief_bypass_allowed()` runs **first** via `_wmatic_stable_p2_relief_override_active()` — **before** PROFIT_TAKE / `MAIN_STRATEGY` dust defer and `$10` `min_notional_usd` (MAIN_STRATEGY checks relief before `entries_paused` entry gate).
  - Logs: `[nanoclaw] P2 relief check | wm=… | notional=… | signal=… | allowed=…`; `[nanoclaw] P2 RELIEF OVERRIDE ACTIVE | WMATIC=$X | notional=$Y | bypassing min_notional`; `[nanoclaw] Main strategy small profit take allowed (P2 relief)`.
  - **Force small profit take** (TEMPORARY SPRINT FIX — capital rotation): `state.profit_take_rotation.cycles_since_exit` increments each `determine_trade_decision`; resets on successful WMATIC→stable exit. After tiered idle cycles without a WMATIC→stable profit take, stack/notional meet force floors (healthy: wm **≥ $5.5**, notional **≥ $8**; low/moderate force notional **≥ $10**; long-idle **low stack only** can drop notional to **$1.35**; long-idle lowers force wm to **$1.50** on all tiers) and force-allow P2 relief — bypasses standard P2 wm / notional / signal gates and **`min_notional_usd`** like the override path. Log: `[nanoclaw] FORCE small profit take | WMATIC=$X.XX healthy, no exit for N cycles | notional=$Y.YY | bypassing min_notional`; P2 reason `force_no_exit_cycles`.
  - **Aggressive gas protection (May 2026)**: `_MAIN_STRATEGY_DUST_DEFER_NOTIONAL_USD = 8.0` — MAIN_STRATEGY dust defer for WMATIC→stable uses **$8** effective min when no bypass lowered `min_notional` (allows **$8–$9.99** through dust defer vs **$10** `MIN_TRADE_USD`; still blocks **$2–$7** micro exits).
  - **Tiered P2/force (Signal-Driven Rotation — May 2026)**: reduces over-reliance on high WMATIC balance via **`stack_tier`** (`low` / `moderate` / `healthy` in `modules/swap_executor.py`):
    - **Low** (stack **< $7**): P2 wm **$5**, signal **0.45**, force wm **$5**, force notional **$10**, force after **5** idle cycles.
    - **Moderate** (**$7–$15**): P2 wm **$12**, signal **0.50**, force wm **$12**, force notional **$10**, force after **5** cycles.
    - **Healthy** (≥ **$15**): P2 wm **$7**, signal **0.55**, force wm **$5.5**, force notional **$8**, force after **4** cycles.
    HOLD profit snapshots are ignored for relief scoring on low stacks so small WMATIC→stable exits can still clear dust/min guards.
  - **Long-idle fallback (May 2026)**: after **3** / **6** / **8** cycles without a WMATIC→stable exit (low / moderate / healthy tier), **`long_idle_active`** lowers force wm floor to **$1.50** on all tiers; **only low stacks (< $7)** also drop force notional floor to **$1.35** (moderate/healthy keep tier force floors **$10** / **$8**). Log: `[nanoclaw] MAIN_STRATEGY long idle fallback | …`.
  - **Anti-churn accumulate guards (May 2026)**: `MAIN_STRATEGY_ACCUMULATE_COOLDOWN_CYCLES` (default **8**) blocks `USDT→WMATIC` for N cycles after each successful WMATIC→stable exit (`profit_take_rotation.cycles_since_exit`). `MAIN_STRATEGY_ACCUMULATE_MAX_WMATIC_USD` (default **18**) defers buys when WMATIC stack is already at target. **`MAIN_STRATEGY_PNL_RECOVERY_MODE`** (default **true**, May 2026) pauses **all** idle/mild-loss/P2 micro rotations below **`MAIN_STRATEGY_PNL_RECOVERY_IDLE_MIN_NOTIONAL_USD`** (default **$8**); raises long-idle floor from **$1.35** via **`MAIN_STRATEGY_PNL_RECOVERY_ROTATION_MIN_NOTIONAL_USD`**; adds **`MAIN_STRATEGY_PNL_RECOVERY_LONG_IDLE_CYCLE_BONUS`** (default **+3** cycles); disables mild-loss **fast** (1-cycle) path; also triggers when **`control.json`** `max_copy_trade_pct ≤ MAIN_STRATEGY_RECOVERY_MAX_COPY_PCT_THRESHOLD` (default **0.06**). `control.json` **`paused=True`** takes precedence over accumulate defer. Env-tunable in `config.py`.
  - **Mild-loss micro rotation (May 2026)**: optional (`MAIN_STRATEGY_MILD_LOSS_ENABLED`, default **true**). HOLD **-7% to -1%**, WMATIC **$5–$10**, **1+** idle cycle — only when capped sell (30%, max **`MAIN_STRATEGY_MILD_LOSS_MAX_NOTIONAL_USD`** = **`MAIN_STRATEGY_ROTATION_MIN_NOTIONAL_USD`**, default **$8**) can clear the rotation floor. Typical **$5–$10** stacks no longer emit **$1–$3** micro exits. Bypasses **`MIN_TRADE_USD`** only for **$8–$9.99** notional when stack is in band. Logs unchanged (`MILD-LOSS RECOVERY BYPASS ACTIVE`, etc.).
  - **Mild-loss fast rotation**: same band + **WMATIC qty > 10** + healthy USDT + **1** idle cycle + notional ≥ rotation min; log `[Main Strategy] Mild-loss fast rotation | …`.
  - **Idle WMATIC rotation sell (Signal-Driven Rotation — May 2026)**: when stack is **below** `MAIN_STRATEGY_TP_TRIGGER_WMATIC_USD` (~$52) and idle cycles meet tiered P2/force thresholds (`_main_strategy_idle_rotation_sell_decision`), prefers WMATIC→USDT over accumulate. **35%** sell when stack **< $7** (notional floor **`MAIN_STRATEGY_IDLE_ROTATION_NOTIONAL_FLOOR_LOW`**, default **$1.35**); **28%** when healthy tier; else **`MAIN_STRATEGY_RESERVE_SELL_FRACTION`**. Reasons: `low_wmatic_idle_rotation`, `moderate_wmatic_idle_rotation`, `healthy_wmatic_idle_rotation`.
  - **Stable rotation fallback (Signal-Driven Rotation — May 2026)**: after idle WMATIC→stable cycles, `determine_trade_decision` may return an executable **USDC→EQUITY** X-SIGNAL plan before default USDT→WMATIC accumulation. **Healthy stack**: **6+** cycles, stables **≥ $50**, `signal_strength ≥ 0.75`. **Low stack (< $7)**: **3+** cycles, stables **≥ $30**, `signal_strength ≥ 0.60`. Logs: `[nanoclaw] Signal-Driven Rotation: stable fallback | …` and `🔍 DECISION PATH: MAIN_STRATEGY_STABLE_ROTATION_FALLBACK`.
  - **Main-strategy observability**: each cycle logs `[nanoclaw] MAIN_STRATEGY_STATUS` with **`stack_tier`**, **`quiet_blocker`**, **`long_idle_active`**, **`cycles_to_long_idle`**, low/moderate flags, cycles since exit, stables, profit-take reason, **`activity`**, **`idle_rotation_eligible` / `idle_rotation_note`**, tiered P2/force thresholds, stable-fallback readiness + min signal; P2 checks add **`stack_tier`** and **`cycles_since_exit`**. `[nanoclaw] MAIN_STRATEGY_OUTCOME` reports direction, actionable, quiet, **`quiet_reason`**, note. Force log uses **`{tier}_stack`** (e.g. `low_stack+long_idle`). WMATIC band exits also emit `DECISION | branch=MAIN_STRATEGY` with reasons `wmatic_high_take_profit`, `usdt_reserve_protection`, `wmatic_low_cut_loss`, `low_wmatic_idle_rotation`, `rotation_priority_defer_buy`, etc. Open-trade TP uses `DECISION | branch=PROFIT_TAKE` from `evaluate_take_profit` (`TP_HIT`, `TRAILING_STOP_HIT`, `HOLD`, …).
  - Sprint goal: aggressive capital rotation from small seed WMATIC back into USDC/USDT (and short X-SIGNAL holds when WMATIC profit-take is idle). Monitor fill rate and gas drag before keeping thresholds.

## **Key `.env`** (defaults in `.env.example`; production overrides freely)

Examples: `RPC`, `COOLDOWN_MINUTES`, `ENABLE_X_SIGNAL_EQUITY`, `X_SIGNAL_EQUITY_MIN_STRENGTH` **(default template 0.60; tighten in prod if desired)**,
`X_SIGNAL_ROTATION_PRIORITY_THRESHOLD` **(defaults to `X_SIGNAL_STRONG_THRESHOLD`; lower only for cycle precedence)**,
`X_SIGNAL_ROTATION_MIN_UPSIDE_PCT`, `X_SIGNAL_MIN_ACTIONABLE_STRENGTH`, `X_SIGNAL_MIN_UPSIDE_PCT_FOR_WEAK` **(0 = filter off)**,
`SWAP_SLIPPAGE_BPS`, `LOG_PREFIX`, Polygon token addresses (`USDC`, `WMATIC`, `ROUTER`), and `MIN_TRADE_USD` (hard execution floor for stable-in BUY notional; `FIXED_TRADE_USD_MIN` is reconciled to never sit below it). **Temporary:** in `nanoclaw/strategies/signal_equity_trader.py`, X-SIGNAL `USDC_TO_EQUITY` buys with `abs(signal_strength) >= 0.85` may clear the hard floor at notional down to `_X_SIGNAL_MIN_SIZE_OVERRIDE` (**7.5** USD) and the post-gas effective floor down to `_X_SIGNAL_MIN_EFFECTIVE_OVERRIDE` (**7.0** USD); logs include `[nanoclaw-av] X-SIGNAL small size allowed (high conviction bypass)` and `[nanoclaw-av] X-SIGNAL effective size allowed (high conviction bypass)`. Same path: halved per-asset cooldown when not force-eligible (`[nanoclaw-av] X-SIGNAL high-conviction cooldown bypass`); `abs(signal_strength) >= 0.90` may lift dynamic size toward **$9.25** (`[nanoclaw-av] X-SIGNAL boosted sizing for very strong signal`).

Load order: **`python-dotenv` loads `.env` only** (repo root). Runtime tuning lives in `.env`; **`nanoup` rebuilds `.env` from `.env.example`** while preserving secrets, RPC keys, and **`WALLET=`** (`nanoclaw/env_sync.py`). **`MIN_POL_FOR_GAS`** is **always merged from the template** on nanoup (`ENV_APPLY_FORCE_TEMPLATE_KEYS`, default **0.15**; code floor `max(0.12, env)`). Runtime JSON (**`trade_exits.json`**, **`bot_state.json`**, **`control.json`**) is gitignored — never commit. Update `.env.example` when promoting non-secret defaults, then VM `pull`/`nanoup`.

### Canonical VM env workflow (single file)

1. **`cp .env.example .env`** once; fill secrets in `.env` only (never commit `.env`).
2. **`NANOUP_AUTOSTASH=1 nanoup`** — refreshes `.env` from `.env.example`, keeps preserved keys from existing `.env`.
3. **Tune stage knobs** — either edit `.env.example` + commit + `nanoup` on VM, or temporarily edit `.env` (knowing the next `nanoup` may overwrite keys that are not on the preserve list; **`WALLET=`** is preserved).

## v2.8.x PnL / ops stabilization (reporting + template)

- **`WALLET TOTAL USD` log** includes **`STABLE_USD`** (USDT+USDC) from the same `get_balances()` call as other fields.
- **`scripts/pnl_report.py`**: prints **Stables USD (USDT+USDC)** first, labels **WMATIC** as **token qty (not USD)**, optional **RPC read suspect** when stables ≈ 0 but TOTAL is material; parses both new and legacy `WALLET TOTAL USD` lines. Template sets **`USDC_NATIVE`** (native Polygon USDC) alongside **`USDC`** (USDC.e) so stable totals match wallets that hold both.
- **`scripts/nanohealth.py`** + **`nanoclaw/rpc_health.py`**: operator one-liner + library check that **`connect_web3()`** succeeds and **`chain_id == 137`**; **`nanoup` / `nanorestart`** run it automatically; same **`nanohealth`** alias/shim as other `nano*` commands.
- **`.env.example`**: **`MAX_GWEI=150`** so `nanoup` on VM stops defaulting swaps/AUTO-USDC to `gas_ok=False` during typical Polygon congestion (adjust per ops).
- Full **seed-numeraire PnL** and public reconciliation are still **v2.9+** (see backlog below).

## Strategic release train (big picture)

Directional milestones only—**capital scales when gates pass**, not on calendar vanity: **`nanohealth` green**, reconciled **stables vs explorer**, **bleed rate** and **drawdown** within policy. Dates below are **targets**, not commitments.

| Train | Intent |
|--------|--------|
| **v2.8.0** | First **credible PnL benchmark**: `WALLET TOTAL USD` / **`STABLE_USD`**, dual USDC (`USDC` + `USDC_NATIVE`), `pnl_report` + **RPC read suspect**, **`nanohealth`**, VM runbook + template hygiene (`ANKR_RPC_KEY` excluded, no keyed URLs in git). **Tag** when stage consistently matches wallet truth under healthy RPC. |
| **v2.9.x** | **Operator-grade PnL** (single seed numéraire, compact public reconcile), green-env hardening (e.g. scheduled **`nanohealth`**, alerts), align remaining **on-chain USDC** reads with both USDC contracts where still singleton. |
| **v3.0.0** | **Positive PnL razor focus** → **production ramp**: staged capital (e.g. **~\$1k** start, **+\$5k** first week, **\$10k+** second week)—**every step performance- and risk-gated**. No material scale until v2.8 benchmark + v2.9 trust model prove out. |
| **v3.0.1** | **Code cleanup & debt** (**after** v3.0.0 validates edge): see **v3.0.1 — code cleanup backlog** below—do **not** starve PnL milestones for refactors. |
| **v4.0.0** | **Scale trajectory** toward **~\$100k** notionally at risk (stretch **end-May → mid-Jun 2026** at worst **if** risk + data quality hold). Likely **requires** verified persistence / audit path (see **DB Migration Discussion**). |

### v3.0.1 — code cleanup backlog (scheduled post–v3.0.0 edge proof)

- **Network identity**: one **`CHAIN_ID` (or equivalent)** story; reduce scattered literal **`137`** in swap / 1inch payload builders where safe.
- **Exceptions**: narrow **`except Exception`** in execution + reporting hotspots; carry **explicit reason** to logs (aligns with **Urgent delta checklist**).
- **Façade vs modules**: trim duplication and dead imports between **`clean_swap.py`** and **`modules/*`** without behavior churn.
- **Coverage**: raise **`swap_executor.py`** / **`clean_swap.py`** toward repo baseline **before** aggressive prod sizing (see **Release safety gates** coverage notes).
- **Archive (`archive/`)**: ensure deploy / packaging paths never ship it; periodic pruning.

## Planned — v2.9 backlog
- **Operator docs shipped (v2.8.x)**: **`docs/readme-vm-update.md`** explicit RPC + **`MAX_GWEI`** checklist; **`docs/OPERATOR_SEND_USDC_POLYGON.md`** for funding **`WALLET=`** on Polygon. (VM may stay the deploy source of truth for a tagged **v2.8**; fold doc-only deltas into the **v2.9** branch when you open it—no requirement to push from every local Cursor sandbox.)
- **Green environment (v2.9)**: Treat **RPC + chain truth** as a **hard gate**. **`nanohealth`** (and the same check at the end of **`nanoup`**) answers: can we reach Polygon PoS (**137**) with the configured endpoint chain? **If unhealthy:** fix `.env` / egress / provider first — `nanostatus` / `nanopnl` / swap logs are not trustworthy until then. **Secrets hygiene:** provider tokens (**`ANKR_RPC_KEY`**, keyed RPC paths) must **never** appear in **`.env.example` / git**; if one ever hit **`origin`**, **rotate at the vendor** and update **VM `.env` only**. Extend automation later (e.g. cron **`nanohealth`**, alerts) without duplicating probe logic.
- **Trustworthy PnL (v2.9 — must fix, not polish)**: Today’s `nanostatus` / `nanopnl` / session % are **not operator-grade** when RPC fails, price feeds drift, or totals mix **stables vs mark-to-market**. **v2.9 goal:** define **one seed accounting line** (pick **USDC xor USDT** as the numeraire, not both interchangeably) with an **explicit snapshot time** and **`delta = current_same_basis − seed` in USD** as the **headline PnL** for “did we make money in stables.” **Do not** pretend that single number explains **WMATIC/WETH/POSI** price moves—that is **inventory MTM**, a **separate** series (defer full split to **v3.0** if needed, but v2.9 must stop shipping misleading % labels off wrong totals).
- **Wallet-wide MTM vs MetaMask (v2.9)**: For “everything under the sun” on **one `WALLET=`**,” add either **quotes for every material token** (via **`followed_equities`** / routers) or a named **`unmodeled`** USD bucket fed from explorer-style token lists—so the **sum of reported parts** can be reconciled to **Polygonscan + MetaMask** without silent gaps.
- **Internal vs public reconcile (v2.9)**: Bot logs and **public** sources (wallet UI, block explorer token balances) must be **reconcilable**; emit **compact deltas** (e.g. stablecoin bucket, total wallet-truth, discrepancy flag) on a schedule—not every line every cycle unless debugging.
- **Event store + verified flag (v3.0 direction)**: Move toward an **append-only event DB** (swaps, snapshots, reconciliations). A **separate process** may mark rows **verified** against **public** on-chain reads (or indexer); after that, dashboards can trust DB as read model. **v2.9** can stay file/log/CSV-based if the **math and seed definition** are fixed first.
- **Env ergonomics**: Revisit `nanoenv_apply` preservation list vs operator knobs (`MAX_GWEI`, X-Signal AUTO-USDC thresholds, etc.) so frequent VM tuning survives `nanoup` without accidental resets—or document one blessed workflow explicitly in `docs/readme-vm-update.md`.
- **Cycle observability (@aniki, post-v2.8.0)**: Persist a monotonic **`cycle_seq`** (or per-run UUID) in `bot_state.json` and print it on **`WALLET TOTAL USD`**, **`Cycle done`**, and skip/trade lines so each loop has an **explicit identity** (wall-clock + line order is not enough across restarts and concurrent tools).
- **Force one cycle (@aniki, post-v2.8.0)**: One-shot **bypass global cooldown only** (e.g. `NANOCLAW_FORCE_CYCLE=1` or `python clean_swap.py --force-cycle`), still honoring lock + risk guards—**today** use **`COOLDOWN_MINUTES=0`** temporarily or set **`last_run`** to **`0`** in **`bot_state.json`** before the next tick (see reproduction block below).
- **POL auto top-up vs real swap cost (@aniki, post-v2.8.0)**: **`AUTO_TOPUP_POL`** / **`ensure_pol_for_trade`** compare POL to **`effective_pol_floor()`** = `max(MIN_POL_FOR_GAS, estimated_swap_gas × urgent_gwei × POL_GAS_RESERVE_MULTIPLIER)` (template **`MIN_POL_FOR_GAS=0.15`**, code floor **`max(0.12, env)`**). Startup runs AUTO-POL **before** router approval; low-POL wallets skip forced max-approve instead of crashing. On congested Polygon, stale low floors (e.g. **0.005**) caused skipped top-ups and swap gas failures — fixed via force-template merge on **`nanoup`** and dynamic reserve in **`modules/runtime.py`**.
- **Gas vs AUTO-USDC**: Dedicated max-gwei ceiling for AUTO-USDC top-up (decouple from global swap gas cap) plus tests/docs. (May 2026: partial — `ensure_usdc_for_x_signal(high_conviction=True)` now mirrors X-SIGNAL trade-path gas bypass — uses `URGENT_GWEI` ceiling, then bypasses gas-price check entirely while still requiring `pol_ok`. Stops the dust-trap loop where X-SIGNAL trades execute under high-conviction gas override but the AUTO-USDC funding leg is blocked at `MAX_GWEI`, leaving USDT idle. Decoupled `AUTO_USDC_MAX_GWEI` env knob still pending.)
- **WMATIC USD price sanity**: Fallback / bounds when oracle-style feed drifts vs spot (reduces bogus dust sizing).
- **PnL/reporting polish (mechanical)**: Clarify `nanostatus` / `nanopnl` labels for **WMATIC quantity vs USD** so totals and components cannot be misread side-by-side (**not** a substitute for the trust model above).
- **Multi-chain custody & consolidated PnL (@aniki, v3.0 or post–v2.9)**: Same EOA on **Ethereum + Polygon** (and others) breaks “one `TOTAL`” until we **read and mark** non-Polygon holdings (RPC/indexer per chain), add an explicit **operator snapshot** (e.g. periodic **off-Polygon book USD** in config/JSON), or split reports into **per-chain series**. **v2.8** stays **Polygon-truth**; a unified MetaMask all-network headline is **this** item—not a reason to halt Polygon strategy while mainnet treasury sits idle.

### Cross-check vs wallet UI (May 2026)

- If **MetaMask / Polygonscan** shows **non-zero USDC** on **`WALLET=`** but **`real_cron.log`** prints **`USDC=$0`** and **`fallback_after_all_rpcs_failed`**, treat the UI as **ground truth for balances** and the log as **degraded telemetry** until RPC/read paths are fixed. **AUTO-USDC** may be redundant when stables exist on-chain—symptoms often mean **mis-read**, not “need more top-up.”

## Recent implementation notes (April 2026)

- Unit tests for take-profit paths, swap path candidates, and X-Signal threshold helper (`tests/unit/`).
- No non-core alerting layers in-scope; prioritize strategy code and deterministic logs.

## Today's learnings (27 May 2026 — Stage liveness: reduced HIGH-risk + low-stables dust rebuild)

- **Incident (Instance A @ `22f96757`)**: After two ~$10 LINK BUYs, `STABLE_USD≈$9.76` → perpetual `Risk=HIGH`, `buy_size_multiplier=0.00`, `defensive_pause`, and `main_strategy_dust_deferred` on ~$6.48 `WMATIC_TO_USDT` (USDT reserve path). Bot looked stuck: no new BUYs, no LINK sells, no stable recycle.
- **Ship package (`0ee1302a` + follow-ups)**:
  1. **`ALLOW_REDUCED_HIGH_RISK_XSIGNAL`**: On HIGH buffer risk, if `TOTAL>$130` and eligible BUY signal `≥0.80`, allow **`buy_size_multiplier=0.40`** and clear `defensive_pause` for that cycle (not a full block).
  2. **`MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_*`**: When stables `<$15`, portfolio `>$130`, and MAIN wants a **$5–$8** WMATIC→stable exit, bypass dust defer (rate-limited every 3 cycles).
  3. **`MAIN_STRATEGY_RESERVE_PREFER_USDC`**: USDT reserve protection sells **WMATIC→USDC** when combined stables are below the X-SIGNAL high buffer (~$15), so rebuild feeds the bucket BUYs use.
  4. **`REDUCED_HIGH_RISK_MIN_TRADE_USD=8`**: Floors scaled HIGH-risk BUY size so 0.40× does not fall below `MIN_TRADE_USD`.
- **Post-deploy grep (healthy unblock)**: `HIGH risk reduced sizing applied`, `Main Strategy dust conversion to USDC`, `STABLE RESERVE PROTECTION (USDC)`, `defensive_pause skipped for reduced HIGH-risk`, and eventually `Risk=LOW` or a small `USDC_TO_EQUITY` fill — not endless `dust_deferred` + `DEFENSE ACTIVE` with `0.00` multiplier.
- **Disable rollback**: `ALLOW_REDUCED_HIGH_RISK_XSIGNAL=false` and/or `MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_ENABLED=false` restores prior full HIGH block / dust defer behavior.

## Today's learnings (27 May 2026 — PnL turnover / rotation metrics)

- **Operator ask**: Distinguish **velocity** (on-chain swap count from `Swap executed successfully!`) from **turnover** (USD notional swapped ÷ current seed TOTAL). A `turnover_multiple` of 1.0 means ~$120 swapped on a ~$120 book; 10.0 means ~$1200 notional — not 10 fills.
- **Implementation**: `scripts/pnl_report.py` adds `sum_turnover_usd()` parsing on-chain `[nanoclaw] TRADE_ATTRIBUTION tx=0x… sz≈…` lines (CYCLE unix_ts attribution, tx dedupe); `format_turnover_lines()` beside existing velocity in the ROTATION block and `--velocity-only` / `nanovel`. Plan-only `TRADE_ATTRIBUTION | Asset=…` lines (no `tx=`) are ignored. Seed for multiple = live TOTAL from `get_current_balance()`, not lifetime CSV.
- **`.env.example`**: unchanged (no new env knobs).

## Today's learnings (26 May 2026 — Cleanup #5: defensive_pause / cycle risk uses combined stables)

- **Incident**: Post–Cleanup #4 deploy, `try_x_signal` logged `Risk=LOW | stable_usd=$40.17` and `X-SIGNAL PLAN SELECTED`, but the same cycles hit `TRADE SKIPPED: defensive_pause (risk=HIGH) — pausing X-signal BUY entries`.
- **Root cause**: Cleanup #4 fixed `_assess_x_signal_buy_risk()` (plan-level BUY defense) to use combined stables, but `_x_signal_buy_risk_level()` (used by `_cycle_risk_level` → `_defensive_pause_state`) still compared **USDT-only** to buffer thresholds. With `usdt=$9.27` and `usdc=$30.90`, cycle gate saw HIGH while plan assess saw LOW.
- **Fix (Cleanup #5)**: Extracted shared `_x_signal_buy_risk_level_from_buffers(stable_usd, wmatic)`; `_x_signal_buy_risk_level` and `_assess_x_signal_buy_risk` both use combined stables for HIGH/MEDIUM buffer tiers. `_cycle_risk_level` passes `balances.usdc`. Tests: `test_signal_x_signal_buy_risk.py` (cycle gate cases), `test_defensive_pause.py` (HIGH only when stables genuinely low).
- **Post-deploy grep**: With `STABLE_USD≥$40`, cycles should **not** show `defensive_pause ... pausing X-signal BUY`; expect `cycle_selected` and/or real tx hash (or a concrete non-pause skip reason).

## Today's learnings (26 May 2026 — Cleanup #4: X-SIGNAL BUY defense / rotation unblock)

- **Incident**: Post–Cleanup #3 deploy, LINK_ALPHA `signal=0.810` force-eligible every cycle but `X-SIGNAL BUY DEFENSE ACTIVE | buy_plans_paused=True | reasons=usdt_below_high_buffer` with `USDT=$9.27`, `USDC=$30.90`, `STABLE_USD≈$40.17`. `high_trigger = PROTECTION_FLUCTUATION_USDT_THRESHOLD (12) + 3 = $15`.
- **Root cause**: `_assess_x_signal_buy_risk()` compared **USDT-only** to the buffer thresholds, while X-SIGNAL equity BUYs spend **USDC** (`USDC_TO_EQUITY`). Low USDT with ample USDC falsely tripped HIGH and blocked rotation.
- **Fix (Cleanup #4)**: Buffer checks (HIGH `usdt_below_high_buffer`, MEDIUM `usdt_below_medium_buffer_and_wmatic_high`) now use **combined stables** (`balances.usdt + balances.usdc`, same as `STABLE_USD`). `very_large_usdt_divergence` remains USDT snapshot vs on-chain USDT. Operator logs (`X-SIGNAL BUY RISK`, `BUY RISK CONTEXT`, `BUY DEFENSE`) print both `usdt=` and `stable_usd=` plus triggers. `_x_signal_buy_risk_level` / `_cycle_risk_level` unchanged (USDT paths). Tests: `tests/unit/test_signal_x_signal_buy_risk.py`.
- **Post-deploy grep**: With `STABLE_USD≥$40`, cycles should **not** show `buy_plans_paused=True` solely for `usdt_below_high_buffer` when LINK is force-eligible.

## Today's learnings (26 May 2026 — Cleanup #3: PnL accounting drift)

- **Incident**: Wallet TOTAL $121.33 (MetaMask, Polygon tab) vs bot TOTAL $111.08 (`nanopnl` → `RUNTIME WALLET TRUTH (in-process compute_authoritative_total_usd)`). Gap $10.25, suspiciously equal to the LINK_ALPHA buy that fired in the same cycle (tx `1de9409c`). Component delta: stables +$8.56 OVER, LINK -$17.96 SHORT, POL -$0.85 SHORT, WMATIC 0.
- **Root cause #1 — POL appeared excluded but was actually invisible**: POL was already in `total_portfolio_usd` arithmetically (`pol * POL_USD_PRICE`, runtime.py:923), but the `WALLET TOTAL USD` log line only printed POL **quantity** — POL_USD was never emitted, so operators had to back-solve the $0.85 slice from the gap.
- **Fix #1 (Cleanup #3 part 1)**: Added `Balances.pol_usd` (= pol × POL_USD_PRICE), populated in `get_balances()` and `write_portfolio_history_snapshot()`. The `WALLET TOTAL USD` log line now prints `POL_USD=$X.XX` between POL qty and FE_USD. Inserted after WMATIC so `AUTHORITATIVE_TOTAL_PATTERN_V2` regex (read-only fallback for historical logs) is unaffected. Tests in `tests/unit/test_runtime_authoritative_total.py` (region: POL_USD operator visibility).
- **Root cause #2 — LINK MTM silent undercount**: `_followed_equity_tokens_usdt_usd` used live on-chain quote when `> 0` and only fell back to `bal × current_price_usd` when **all** four quote tiers returned 0. A degraded pool / large-size price impact (5.676 LINK MTM'd at $35.78 vs spot × bal = $53.52) silently undercount TOTAL — the live quote was non-zero, just undervalued.
- **Fix #2 (Cleanup #3 part 2)**: Flipped `current_price_usd` to a **true fallback FLOOR**. Effective per-asset USD = `max(live_quote_usdt, bal × current_price_usd)`. Operator diagnostic `FE_USD FALLBACK FLOOR APPLIED | sym=… | live_quote_usdt=… | fallback_total_usd=… | contributed_to_total=…` fires when fallback wins, so the gap against MetaMask is logged at the moment it happens. Operators MUST refresh `current_price_usd` in `followed_equities.json` periodically — a stale fallback above true spot will overstate TOTAL. Tests in `tests/unit/test_runtime_inventory_mtm.py` (region: FE_USD fallback / visibility regression).
- **Root cause #3 — Stables ±$8.56 drift**: `_total_usdc_balance` already case-insensitively dedups USDC.e + USDC_NATIVE, and `get_balances()` reads USDT fresh per call (no module-level cache). Steady-state arithmetic can't produce the observed gap; the most likely cause is an in-flight swap reservation racing the balance reads (LINK buy fired same cycle). Acceptance criterion A explicitly defines steady-state as the bar, so this is parked.
- **Fix #3 (Cleanup #3 part 3)**: No behavior change — added integration-level regression tests at the `get_balances()` surface in `tests/unit/test_runtime_usdc_native.py` (region: stables drift regression). Pins (a) both USDC variants reach `Balances.usdc` via exactly one `balanceOf` call each, (b) case-insensitive dedup prevents double-counting on operator typo, (c) USDT is read fresh per call.
- **Root cause #4 — WBTC balance-read spam**: `.xsignal_blocked_symbols` containing `WBTC_ALPHA` only gates trading, not inventory reads. The FE_USD scan still tried to read `WBTC_ALPHA` (0x1BFD6703…6C834E, `BadFunctionCallOutput`) every cycle, emitting `BALANCE READ FAILED` lines indefinitely.
- **Fix #4 (Cleanup #3 part 4)**: Added a per-`(token, wallet)` log-once latch (`_BALANCE_READ_FAIL_LOGGED`) in `get_token_balance`. First failure emits the existing line plus `(further failures for this token+wallet suppressed for process lifetime)`; subsequent failures stay silent and still return 0.0. Per-token AND per-wallet so a fresh wallet still gets one diagnostic. Tests in `tests/unit/test_runtime_get_token_balance.py`.
- **Test count**: green gate 47 → 61 passing. New test regions documented above. `pol_usd` added as a sixth field on `Balances`.
- **Parked**: in-flight swap reservation race (the most likely cause of the May 26 stables drift). Acceptance criterion A defines wallet-vs-bot match within $1 only in steady state; an explicit re-read after swap settlement is a candidate for Cleanup #4. The original 9 pre-existing test failures (profit-take logic, mock signature mismatches, live RPC bleed) are also assigned to Cleanup #4.

## Today's learnings (24 May 2026 — startup-crash landmine)

- **Incident**: Live bot crash-looped on startup on 2026-05-24. Every restart hit `clean_swap.py:249 _force_max_approval(...)` → `swap_executor.py:72 w3.eth.send_raw_transaction(...)` → `Web3RPCError: insufficient funds for gas` (POL balance ~0.0254, approve tx cost ~0.0496 POL). Crontab's 2-min watchdog respawned the same crash so AUTO-POL never got a chance to top up.
- **Root cause**: legacy `_force_max_approval` wrapper passed `force=True` to `ensure_startup_router_approval`, bypassing the allowance pre-check inside (`if not force and allowance >= min_allowance:`). With allowance already at MAX (the common case), the safe path is to skip — not to broadcast a fresh approve that can't fund itself.
- **Fix (Cleanup #2, 2026-05-26)**: Dropped `force=True` from `_force_max_approval` so the wrapper inherits both the allowance pre-check (skip + return True when sufficient) and the POL pre-check (skip + return False when balance < `approve_gas_units × gas_price × 1.10`). Neither path raises. The interactive code path in `clean_swap.py` (now `ensure_startup_router_approval` at line 254, not the legacy `_force_max_approval` at 249) already had both guards in `bbfa05d9`; this commit closes the wrapper-shaped landmine for any stale caller. Regression tests in `tests/unit/test_force_max_approval_resilience.py` pin the three cases (allowance-max → True, POL-low → False, never raises).

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
- Env parity workflow (VM -> repo template):
  - `python scripts/nanoenv_example.py --write` (sync `.env.example` from `.env`, secrets blanked)
  - `python scripts/verify_env_example_keys.py` (check config coverage + `.env`/`.env.example` drift when `.env` exists)
  - Numeric/bool env parsing treats empty values as defaults (safe for optional blank aliases in `.env.example`)
  - Canonical reusable sequence: `docs/readme-vm-update.md` (standard flow + exceptional `.env.example` -> `.env` path)

## Urgent delta checklist (do not skip)

- TODO (priority, platform-side hardening): enable protected branches + required CI checks + GitHub secret scanning/push protection as documented in `docs/REPO_HARDENING.md`.
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
- Update operator-facing docs in the same task when commands/workflows/config behavior changed (`README.md`, `docs/*`, and this file when relevant).
- Keep `.env.example` aligned with any new/changed env-driven behavior in code/scripts.
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
  - **PowerShell 5.x** (local): run the two lines above separately, or use `; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }` between them — avoid **`&&`** unless **pwsh** 7+ (see **`docs/DEV_WORKFLOW.md`**).
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

## TODO & Backlog (2 May 2026)

### P0 BLOCKER: Only WMATIC_ALPHA Trading (X-Signal Asset Rotation Broken) ✅ FIXED
**Status**: Fixed  
**Root causes identified & resolved**:
- ✅ Symbol mismatch: `followed_equities.json` "WETH" → "WETH_ALPHA"
- ✅ JSON field mapping: `timeline_hours` → `earnings_days` (code was looking for earnings_days field)
- ✅ Critical bug: `try_x_signal_equity_decision` function was missing `return decision` statement (had `pass` instead)
- ✅ Enhanced diagnostics: improved logging when build_plan fails for assets (now shows signal, equity_balance, block reason)

**Deployment readiness**: Ready to test on stage bot
- Restart bot with: `nanokill && nanoup`
- Monitor logs for asset rotation: should see WETH_ALPHA, WBTC_ALPHA, LINK_ALPHA trading after WMATIC_ALPHA 30-min cooldown
- Confirm in logs: look for "X-SIGNAL EQUITY SUMMARY | Assets checked: 5" (all 5 assets should be eligible)

### P1: Pylance Type Errors (186 errors in clean_swap.py)
**Status**: Backlog  
**Impact**: Editor DX only; no runtime impact  
**Fix**: Use `TYPE_CHECKING` pattern for Web3 imports  
**Effort**: ~30min  

### P1: Code coverage baseline (as of 2026-05-01)
- Overall: 79% | clean_swap.py: 58% | signal_equity_trader.py: 79% | gas_protector.py: 94% | swap_executor.py: 60% | protection.py: 72%

## Design rules

- Builder pattern where used; `.env`-driven; risk-first.

**How to continue in any new thread**  
Use **New Thread Protocol** above plus full steps in **`docs/NEW_THREAD_PROTOCOL.md`**. Snapshot URL: https://raw.githubusercontent.com/krantikaridev/nanoclaw/V2/AI_CONTEXT.md

**Next milestone**

Earnings Volatility Capture Engine v1, while preserving strict hard risk limits and removing artificial profit caps (cooldown, small trade size, low frequency).

## Quick commands (`nano*` convention)

| Command | What it does |
|---------|----------------|
| `nanoup` | Safe update + restart (recommended) |
| `nanohealth` | **`python scripts/nanohealth.py`**: Polygon RPC via **`connect_web3()`**, **`chain_id` 137**, live block; exit non-zero if unhealthy. Runs at end of **`nanoup`** and before **`pnl_report`** in **`nanorestart`**. |
| `nanostatus` | Runs `python scripts/pnl_report.py`: current balances (USDT/USDC/WMATIC/TOTAL), baseline/session/24h PnL, and recent trade hints from `real_cron.log`. Balance source preference is `WALLET TOTAL USD` runtime truth first, then legacy live parser snapshots (`WALLET BALANCE` + `Real USDT`, direct `Real USDT`), then manual correction fallback. Snapshot sanity guard rejects non-finite/negative/unreasonable values before selection. |
| `nanopnl` | Alias of `nanostatus` for fast PnL checks (same runtime-truth-first balance sourcing rules) |
| `nanodaily` | Daily health snapshot: balances, bypass/cooldown/protection counters, commit, TEST_MODE |
| `nanobot` | Live `real_cron.log` stream (`tail -f`) for runtime diagnostics |
| `nanorestart` | **`nanoup`** then **`nanohealth`** then **`pnl_report`** (not merely `nanoup && nanostatus`) |
| `nanokill` | Stop the bot |
| `nanoattach` | Attach to live bot logs |
| `nanoenvsync` | Sync `.env.example` from `.env` (secrets blanked) and verify drift/coverage |
| `nanoenvcheck` | Verify `.env.example` key coverage and drift vs sanitized `.env` |
| `nanoenvstage` | Run env sync/check and stage `.env.example` for commit |
| `nanocommit` | Enforce repo hooks + staged secret guard, then run `git commit` |
| `nanopush` | Run secret scan + env sync/check, stage `.env.example`, then `git push` |

**`sprintmon`** was retired from this tree—use **`nanostatus`** / **`nanopnl`** + **`nanobot`** / **`nanoattach`** instead.

> X-Signal integrates proactive USDC maintenance in `try_x_signal_equity_decision` when USDC drops below `X_SIGNAL_USDC_SAFE_FLOOR`, targeting `X_SIGNAL_AUTO_USDC_TARGET` before BUY decisions (not a separate shell command).

### Stop / restart

```bash
nanokill
nanoup
```


### TODO - High Priority (add 2026-05-03)
- **Sizing bug from Cursor refactor**: Bot deployed full available USDC/USDT balance on high-conviction signals instead of fixed $12–$20 per signal. Happened once (large WMATIC/USDT/WETH buys) before crash. Fix: enforce fixed-size logic + proper balance checks before any swap.
- Investigate why the refactored code ignored COPY_TRADE_PCT / fixed-size logic.
- Add per-trade attribution (which signal/wallet caused each swap) so we can debug future anomalies.
- 1inch readiness gate: once API key registration is completed, validate the live 1inch path end-to-end on VM (quote, spender, tx payload, and receipt logs) and then decide whether to promote it back to preferred executor or keep Uniswap V3 fallback as default.


## Constitution Update — 2026-05-04 (post V2 High-Conviction Task)

**Rule 7 — Never Assume Pushed**  
Never assume code is on GitHub or VM unless you personally verified it with `git log --oneline -5` AND `grep` for the changed logic on BOTH local (Cursor) and VM. This is non-negotiable for every code review.

**Rule 8 — Full Feedback & Improvement Loop (Mandatory)**  
Every task must end with a documented section in AI_CONTEXT.md under “Task Log: [Task Name]” containing:
- What worked
- What didn’t (including unexpected side-effects)
- Bleeding / PnL / risk impact discussion
- Proposed improvements for next iteration
- Dual verification confirmation (Grok + user both confirmed)

**Rule 9 — Sizing & Bleeding Protection**  
Any change to high-conviction sizing must:
- Respect `min_trade_usdc` ($5.00)
- Preserve diversification (do not make 3/4 assets untradeable)
- Include quick PnL vs fee + slippage estimate before aggressive caps
- Default high-conviction cap to $6.00–$8.00 unless bleeding analysis shows otherwise

**Rule 10 — Dual Verification Before “Done”**  
Grok may never say “task complete / loop closed” until BOTH sides have:
1. Run the verification commands
2. Confirmed the exact expected output
3. Agreed the task is working as intended

## Lessons from 4 May 2026 Session (PnL Loop + Small Trade Issue)

### Key Challenges Faced
- Spent excessive time on PnL report (multiple broken versions, parser fragility, stale data).
- Small $4.5 trades continued despite `MIN_TRADE_USD=22` in .env — root cause was hardcoded `_HIGH_CONVICTION_WMATIC_MAX_USD = 4.50` bypass in `nanoclaw/strategies/signal_equity_trader.py`.
- Many suggested .env keys (FLUCTUATION_THRESHOLD, PROTECTION_COOLDOWN_MIN, SLIPPAGE_TOLERANCE, MAX_TRADES_PER_HOUR) did **not** exist in code — only aliases or different keys were used.
- Frequent Cursor pushes + VM behind by 10+ commits caused repeated sync issues.
- Raw `git pull` failed multiple times due to unstaged log files.

### Important Principles
- **Always verify against actual code**, not just .env.example or suggested keys.
- Hardcoded values in strategies are high-risk — they bypass .env settings.
- PnL report should stay **simple and reliable** (one robust parser). Complex time-window logic breaks easily when log format changes.
- Use aliases (`nanorestart`, `nanopnl`, `nanostatus`) consistently — never raw `git pull` without stashing noisy files first.
- Cursor changes on local machine require proper `git stash + pull` on VM.

### High-ROI Priorities Going Forward
1. **Stop small trades permanently** (remove $4.50 WMATIC bypass + enforce MIN_TRADE_USD=22 in execution path).
2. **Add commit hash to every log line** (easy "before vs after commit" performance analysis).
3. **Create one simple daily health command** (shows in 5 seconds: current PnL, last 4h trend, any protection triggers, small trade count).
4. **Avoid further PnL report complexity** until the above are done.

### Todo (Captured)
- [ ] Fix small trade enforcement (one targeted edit in signal_equity_trader.py)
- [ ] Add commit hash prefix to all log lines in clean_swap.py
- [ ] Create `nanodaily` alias for quick health check
- [ ] Keep .env.example and actual code in sync (test already exists)

## Task Log: v2.7 Stage Liveness Recovery (2026-05-05)

### What worked
- Confirmed live swap execution resumed on stage after guard-path fixes and runtime tuning:
  - `0x74a05b137a746b6a6d79097f7a3fc6429bd7ad7020e82a11725473642007d587`
  - `0x168ffde271afd3bab7f8d1733b29dc23ab7cc18c3af2de909f7a2c5938dfb647`
  - `0x2b686cc7e2e73d5d08f88dc8543e1b33bbbb414f4fc11654e5105fbf2b205b60`
- Protection dust defer and downstream fallthrough now observed in runtime logs (`PROTECTION DUST DEFER ... continuing to next strategy`).
- Single-process condition restored (`pgrep -af clean_swap.py` showing one bot process in latest checks).
- Per-trade precedence monopoly reduced by protection latest-open-trade evaluation fix (code + tests merged on `V2`).

### What did not work
- AUTO-USDC still frequently starts but fails to reach floor in some windows (`AUTO-USDC top-up attempted but floor not reached`).
- X-signal BUY paths still show `zero_usdc` blocks during low-USDC phases.
- Fluctuation protection still triggers under low-USDT/high-WMATIC states; when sell notional is below `MIN_TRADE_USD`, it can still defer unless runtime sell fraction is tuned.
- Runtime reporting inconsistency observed: `nanodaily` / `nanopnl` reported `USDC=$0.00` and very high PnL while wallet UI snapshots showed non-zero USDC and materially different total value; reported PnL must be treated as provisional until parser/source reconciliation is completed.

### Bleeding / PnL / risk impact
- Positive operational milestone: bot is no longer fully stuck in non-executing loops; real swaps resumed.
- Risk remains that repeated protection-trigger/defer cycles can dominate decision bandwidth during stressed balance mixes.
- Immediate 2.8 baseline should measure:
  - executed swap count per hour
  - protection-trigger rate
  - deferred-vs-executed protection exits
  - net session delta from start/end `nanodaily`.

### Baseline snapshot for 2.8 kickoff
- Benchmark evidence window (short fast windows on 2026-05-05 UTC) captured:
  - multiple successful swaps with tx receipts
  - protection-trigger + dust-defer events still present
  - no sustained lock-thrash pattern in latest checks.
- Latest observed health snapshot example: `nanodaily` at `2026-05-05 08:49` (stage, `TEST_MODE=true`, total around `$198.10`; use as a provisional anchor only).
- Additional operator check on 2026-05-05 showed divergence between bot-reported balance/PnL and wallet UI totals (including USDC visibility), so 2.8 baseline must be anchored on reconciled live balances first.

### Proposed improvements for next iteration
1. Stabilize AUTO-USDC conversion reliability (path health, min swap sizing, fallback diagnostics).
2. Tune fluctuation branch to reduce dust-defer no-op loops while preserving risk guardrails.
3. Reconcile `nanodaily`/`nanopnl` live balance source selection against wallet truth (USDC visibility + total value) before using PnL percentages as decision gates.
4. Add one-command benchmark capture (`start marker + early-exit success detection + summary grep`) for faster 2.8 loops.

### Dual verification confirmation
- User-side runtime checks: completed (commands and VM logs shared in-thread).
- Assistant-side verification: completed for local code/tests/docs and interpreted VM runtime evidence.

## v2.9 Backlog Entry (post-2.8 phase-1 validation)

### 2.8 phase-1 closure status
- Phase-1 is healthy and behaving as designed: PR1 and PR2 acceptance checks were confirmed on VM logs.
- PR1 accepted: `nanodaily`, `nanostatus`, and `nanopnl` now show the same current total with source `RUNTIME WALLET TRUTH (TOTAL USD)`.
- PR2 accepted: repeated per-asset `zero_usdc` spam after failed AUTO-USDC paths is reduced to one explicit per-cycle short-circuit reason, with no observed lock/cooldown regression.

### Pending for 2.9
1. **USDC contract reconciliation hardening**
   - Runtime still can diverge from wallet UI when stage holdings include a USDC contract variant not included in `.env` (`USDC`/`USDC_NATIVE` mapping).
   - Add a startup/runtime warning when `_total_usdc_balance()` is effectively zero while X-signal requires USDC floor and wallet-level heuristics suggest a likely mapping/config issue.
   - Document and enforce VM expectation: both Polygon USDC contracts configured when needed (`USDC.e` + native USDC).

2. **AUTO-USDC conversion reliability under gas constraints**
   - Current behavior is safe but often blocked by gas guard (`gas_ok=False`), leaving conversion attempts unsuccessful in some windows.
   - Tune policy/thresholds and retry strategy for top-up attempts without weakening risk controls (guard-aware execution policy, bounded retries, and clearer outcome classes).

3. **Fluctuation + dust-defer efficiency**
   - Protection and main-strategy dust defers still consume cycle bandwidth in low-notional windows.
   - Evaluate branch-level notional rules and/or protection sell-fraction tuning to reduce repeated no-op cycles while preserving risk-first behavior.

4. **Operational evidence automation**
   - Promote benchmark capture into a single maintained command/script for release checks (marker -> timed window -> summarized acceptance evidence).
   - Keep PR1/PR2-style acceptance snippets as reusable release gates for future tags.

5. **Status output polish**
   - Investigate `nanodaily` "Small trades bypassed: 0" duplicate line (`0` echoed twice in some runs) and normalize output formatting for operator clarity.
v2.8.1 ACCEPTED - Session PnL >=0 achieved

### nanoup improvement (post-v2.8.1 TODO - high ROI)
- Add flag `NANOUP_PRESERVE_LOCAL_ENV=true` (or make default with AUTOSTASH)
- Behaviour: pull latest code + new .env.example keys, but **preserve existing local .env values** unless .env.example marks a key with `# OVERRIDE_REQUIRED`
- This makes rapid iteration safe without forcing every tweak into .env.example
- Priority: #1 after v2.8.1 acceptance

### v2.9 starter tasks (now open)
1. nanoup improvement (already in TODO)
2. Operator-grade accounting: single numéraire, verified snapshots, wallet MTM vs Polygonscan reconcile
3. Event-store foundations + POL auto top-up logic
4. Monitoring playbook: run `watch -n 300 "nanodaily --lookback 1h && nanopnl"` during office hours

### v2.9 copy-trading benchmarking TODO
- Explore Binance lead trader 4990326484420505601 (30D PnL, ROI, followers, AUM, MDD)
- Compare vs nanoclaw COPY_TRADE_PCT / dynamic sizing / wallet_performance.json
- Add leader-style metrics (win-rate, max-drawdown filter) to copy module


### v2.9 first operator-grade accounting task
- Add simple Polygonscan reconciliation command to nanohealth or a new `nanoreconcile` script (wallet MTM vs on-chain)
- Run once per day to verify runtime truth matches blockchain


### v2.9 high-ROI items (PnL > 0 + Production Readiness)

- **Smarter pre-protection warnings + suggested actions** (High ROI)
  - Add checks before protection triggers (e.g. "USDT approaching threshold while WMATIC exposure is high").
  - Surface suggested actions (pause buys, reduce size, top-up stables, etc.).
  - Goal: Reduce frequency and severity of protection sells that hurt Session PnL.

- **Stables vs WMATIC exposure ratio check** (High ROI)
  - Add a simple ratio or risk score (e.g. Total Stables / WMATIC value).
  - Warn early when the ratio becomes unhealthy (prevents repeated protection cycles).
  - Can be shown in nanoreconcile and nanostatus.
