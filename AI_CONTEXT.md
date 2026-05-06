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
| **`FE_USD`** | **USDT-notional** for **non-core** rows in **`followed_equities.json`** (e.g. **Polygon WETH** `0x7ceB…`)—same `balanceOf` on **Polygon** as stables. **Not** Ethereum-mainnet WETH (`0xC02a…`); MetaMask totals often mix chains. Uses **V2 router**, **QuoterV2**, multihop; optional **`current_price_usd × balance`**. **`FE_USD=$0`** with “WETH” in MetaMask: confirm you’re on **Polygon** token details (contract **`0x7ceB…`**) or expect **zero** on-chain for that asset on Polygon; look for **`BALANCE READ FAILED`** if reads error. |
| **`TOTAL` (runtime)** | **USDT + USDC (both) + WMATIC×price + POL×`POL_USD_PRICE` + `FE_USD`**. Not guaranteed to equal MetaMask’s all-network headline. |

## **Operating Model (roles + loop)**

- Canonical role split and collaboration loop live in `docs/OPERATING_MODEL.md`.
- Keep this file as canonical backlog/process memory; keep role mechanics in the operating-model doc to avoid drift.

## **Developer environments (shell + machine)**

- **Local / Cursor**: Often **Windows + PowerShell** — do not assume **`&&`** (use **`;`** / **`$LASTEXITCODE`** on PS 5.x, or **PowerShell 7+**). See **`docs/DEV_WORKFLOW.md`** § *Shell: Windows vs Linux*.
- **Stage VM**: **Ubuntu + bash** — `nanoup`, `grep`, and **`docs/readme-vm-update.md`** snippets are written for **POSIX**.
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

Protection → Profit take (`evaluate_take_profit`) → **X-Signal equities** (`try_x_signal_equity_decision`) → USDC copy → polycopy/target wallets → main USDT↔WMATIC logic.

Operational focus: correctness of this precedence, USDC liquidity for equity **buys**, and execution on Polygon **chain ID 137** only.

## Execution & observability

- **`followed_equities.json`**: `min_signal_strength` in JSON and `X_SIGNAL_EQUITY_MIN_STRENGTH` in env both apply — **effective floor = max(JSON, env)**. Logged each X-Signal check as `[nanoclaw] X-Signal threshold …`.
- **Polygon test proxies**: current repo config uses Polygon-native staples (WMATIC / WETH / WBTC) plus `_note` where Ondo tickers remain off-chain-Polygon until official listings; replace `address` when real Polygon contracts exist.
- **Logs**: `[nanoclaw]` prefix via env `LOG_PREFIX`; cycle banner; path tags (`🔍 DECISION PATH`). X-Signal emits threshold line, ACTIVE lines, SUMMARY line, and (when a plan exists) checksum `token_in` / `token_out` before swap.
- **Balance logger**: integrated into `clean_swap.py` (`Source=BotLogger`) reading `balance_config.txt` every 600s; no separate `scripts/auto_balance_logger.sh` process needed.
- **Balance logger guardrail**: skips writing snapshots when `balance_config.txt` is missing/empty/invalid to avoid zero-value noise in `real_cron.log`.
- **Fluctuation protection**: `FLUCTUATION` now emits rich trigger context, honors `PROTECTION_FLUCTUATION_COOLDOWN_SECONDS` to suppress repeated force-sell triggers in short windows, and applies `PROTECTION_FLUCTUATION_MIN_SELL_USD` to ignore low-notional noise triggers.
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

## **Key `.env`** (defaults in `.env.example`; production overrides freely)

Examples: `RPC`, `COOLDOWN_MINUTES`, `ENABLE_X_SIGNAL_EQUITY`, `X_SIGNAL_EQUITY_MIN_STRENGTH` **(default template 0.60; tighten in prod if desired)**,
`SWAP_SLIPPAGE_BPS`, `LOG_PREFIX`, Polygon token addresses (`USDC`, `WMATIC`, `ROUTER`), and `MIN_TRADE_USD` (hard execution floor for stable-in BUY notional; `FIXED_TRADE_USD_MIN` is reconciled to never sit below it).

Load order: **`python-dotenv` loads `.env` only** (repo root). Runtime tuning lives in `.env`; **`nanoup` rebuilds `.env` from `.env.example`** while preserving secrets, RPC keys, **`WALLET=`**, **`MIN_POL_FOR_GAS=`** (`nanoclaw/env_sync.py`). Update `.env.example` when promoting non-secret defaults, then VM `pull`/`nanoup`.

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
- **POL auto top-up vs real swap cost (@aniki, post-v2.8.0)**: **`AUTO_TOPUP_POL`** / **`ensure_pol_for_trade`** only run when **`POL < MIN_POL_FOR_GAS`** (default **0.005** in `config.py`). A wallet can sit at **~0.02 POL** (above the floor), **skip AUTO-POL**, then fail the swap with **“insufficient funds for gas”** when **`estimateGas × gasPrice`** exceeds balance. **v2.9+**: gate submits on **dynamic** reserve (estimate + buffer) or raise safe defaults/docs; **today** raise **`MIN_POL_FOR_GAS`** in `.env` (e.g. **0.12–0.25** on congested Polygon) so top-up fires earlier.
- **Gas vs AUTO-USDC**: Dedicated max-gwei ceiling for AUTO-USDC top-up (decouple from global swap gas cap) plus tests/docs.
- **WMATIC USD price sanity**: Fallback / bounds when oracle-style feed drifts vs spot (reduces bogus dust sizing).
- **PnL/reporting polish (mechanical)**: Clarify `nanostatus` / `nanopnl` labels for **WMATIC quantity vs USD** so totals and components cannot be misread side-by-side (**not** a substitute for the trust model above).
- **Multi-chain custody & consolidated PnL (@aniki, v3.0 or post–v2.9)**: Same EOA on **Ethereum + Polygon** (and others) breaks “one `TOTAL`” until we **read and mark** non-Polygon holdings (RPC/indexer per chain), add an explicit **operator snapshot** (e.g. periodic **off-Polygon book USD** in config/JSON), or split reports into **per-chain series**. **v2.8** stays **Polygon-truth**; a unified MetaMask all-network headline is **this** item—not a reason to halt Polygon strategy while mainnet treasury sits idle.

### Cross-check vs wallet UI (May 2026)

- If **MetaMask / Polygonscan** shows **non-zero USDC** on **`WALLET=`** but **`real_cron.log`** prints **`USDC=$0`** and **`fallback_after_all_rpcs_failed`**, treat the UI as **ground truth for balances** and the log as **degraded telemetry** until RPC/read paths are fixed. **AUTO-USDC** may be redundant when stables exist on-chain—symptoms often mean **mis-read**, not “need more top-up.”

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
