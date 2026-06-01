# Agent sprint prompts (May 2026)

Copy one prompt per parallel agent. Parent agent reviews all PRs and runs regression before push.

**Branch:** `V2` (live stage VM) · **Next sprint:** [`docs/AGENT_SPRINT_PROMPTS_V3.md`](AGENT_SPRINT_PROMPTS_V3.md) on branch `V3` — dev only until merge gate passes.

**VM path:** `~/.nanobot/workspace/nanoclaw`  
**Do not commit:** `.env`, API keys, `control.json` operator state

---

## Agent A — RPC probe + cron alert (P0) — **IN PROGRESS (parent)**

**Goal:** Ship `scripts/rpc_probe.py` + `nanoclaw/rpc_probe.py` (per-endpoint probe, redacted URLs, exit 1 when all fail).

**Acceptance:**
- [ ] `python scripts/rpc_probe.py` prints OK/FAIL per endpoint
- [ ] `python -m pytest tests/unit/test_rpc_probe.py -q` passes
- [ ] `.env.example` drops dead `polygon.llamarpc.com`; adds `polygon.drpc.org`
- [ ] `docs/readme-vm-update.md` documents cron: `*/15 * * * * cd … && python scripts/rpc_probe.py --alert`
- [ ] Optional shim `~/.local/bin/rpcprobe` via `nanobot_aliases.sh --install`

**VM verify after deploy:**
```bash
python scripts/rpc_probe.py
nanohealth
```

---

## Agent B — Operating reserve guard (P0)

**Goal:** When `stable_usd < STAGE_SEED_USD × OPERATING_RESERVE_PCT / 100`, defer **new entries** (not protection exits).

**Files:** `config.py`, `modules/swap_executor.py`, `.env.example`, `tests/unit/test_operating_reserve.py`

**Acceptance:**
- [ ] Log line: `[nanoclaw] OPERATING RESERVE FLOOR | defer new entry | stable_usd=… | reserve_floor=… | seed=…`
- [ ] At `$8.91` stables + `STAGE_SEED_USD=132` + `OPERATING_RESERVE_PCT=10` → floor `$13.20` → entries blocked
- [ ] `OPERATING_RESERVE_ENABLED=false` disables guard
- [ ] `STAGE_SEED_USD=0` uses live TOTAL as seed
- [ ] Unit tests cover block / pass / disabled
- [ ] `nanoclaw/env_sync.py` preserves the three new keys on `nanoup`

**Do not:** change FE runway trim thresholds or auto_pause logic in this task.

---

## Agent C — Net PnL after opex (P1)

**Goal:** Extend `scripts/pnl_report.py` / `nanodaily` with **`NET AFTER OPEX`** line.

**Env (`.env.example`):**
```bash
OPEX_MONTHLY_USD=10          # Ankr + misc RPC
HOSTING_MONTHLY_USD=0        # VM if any
GAS_ESTIMATE_LOOKBACK_DAYS=7 # optional: sum from tx receipts later; v1 can be manual env only
```

**Acceptance:**
- [ ] `nanodaily` prints: `Net after opex (est): $X.XX (session) | opex_budget=$Y/mo prorated`
- [ ] Prorate monthly opex to session days elapsed
- [ ] Tests in `tests/unit/test_pnl_report.py` with stub env
- [ ] Update `ROADMAP.md` Phase 0.5 one line when done

**Do not:** change swap execution or RPC code.

---

## Agent D — RPC endpoint health in external layer (P2)

**Goal:** When **all** RPC probes fail for 2 consecutive external-layer ticks (~60s), set `control.json` `paused=true` with reason `auto_pause | RPC all endpoints failed`.

**Files:** `external_layer/control.py`, `external_layer/auto_pause.py` or new `external_layer/rpc_gate.py`

**Acceptance:**
- [ ] Gated by `EXTERNAL_RPC_PAUSE_ENABLED=true` (default false for backward compat)
- [ ] Uses `nanoclaw.rpc_probe.probe_configured_endpoints`
- [ ] Unpauses automatically when probe succeeds AND green gates pass
- [ ] Tests with mocked probes in `tests/unit/test_external_layer.py`

---

## Agent E — Session PnL mark vs trade attribution (P1 ops/doc)

**Goal:** Document and optionally flag when session PnL drop is **mark-to-market** (FE floor / WETH spot) vs **realized trades**.

**Acceptance:**
- [ ] `docs/OPERATOR_PNL_MARK_VS_TRADE.md` — explain `FE_USD AUTO_FLOOR_UPDATE`, MetaMask parity, when to `nanopnl --reset-session` (rare)
- [ ] Optional: `pnl_report.py` line `mark_delta_est: $X (FE spot cache)` when spot cache moved >1% session-over-session
- [ ] No change to trading logic unless adding a read-only diagnostic flag

**Context (31 May 2026):** TOTAL $132→$122 aligned with MetaMask; `FE_USD AUTO_FLOOR_UPDATE | last_good_spot=2022` — not necessarily a bad trade.

---

## Agent F — Tiered FE stable runway (P0 velocity) — **DONE**

**Goal:** When full FE runway blocks USDC→equity BUY (`stable_usd < FE_STABLE_RUNWAY_TARGET_STABLE_USD`), allow **capped** X-SIGNAL buys if stables are above operating reserve, signal ≥ threshold.

**Env (defaults in `.env.example`):**
```bash
FE_STABLE_RUNWAY_TIERED_ENABLED=true
FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL=0.85
FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD=10
```

**Acceptance:**
- [x] Log: `[nanoclaw] FE STABLE RUNWAY TIERED | allow USDC→EQUITY BUY | stable_usd=… | fe_share=… | signal=… | max_notional=$10.00`
- [x] Notional capped at `min(max_notional, stable_usd)` in `try_x_signal_equity_decision`
- [x] Blocked when operating reserve floor active or signal < min
- [x] Tests: `tests/unit/test_fe_stable_runway_tiered.py`, `test_fe_stable_runway_tiered_allows_high_signal_buy_below_runway_target`
- [x] `nanoclaw/env_sync.py` preserves the three keys on `nanoup`

**VM verify after deploy:**
```bash
NANOUP_AUTOSTASH=1 nanodeploy
grep -E 'FE STABLE RUNWAY TIERED|EXEC SUCCESS|TRADE SKIPPED' real_cron.log | tail -20
nano12h
nanohealth | grep -E 'Stables|TOTAL|velocity'
```

Expect at ~$27 stables + WETH signal ≥0.85: tiered allow log, then first capped BUY ≤$10 when edge gates pass.

---

## Agent G — Deposit / withdraw flow tags in PnL (P1) — **DONE**

**Goal:** Separate **capital flows** (deposits, withdrawals, subscription wallet payments) from **trade/mark PnL** so session % is not misleading after top-ups.

**Context (31 May 2026):** Session +19.8% included ~$18 USDT deposit + WETH rotation; operator could not see “real alpha” vs “money in”.

**Files:** `scripts/pnl_report.py`, `nanoclaw/pnl/` or portfolio history helpers, `portfolio_history.csv` schema if needed, `.env.example`, `docs/OPERATOR_PNL_MARK_VS_TRADE.md`, `tests/unit/test_pnl_report.py`

**Env (`.env.example`):**
```bash
PNL_FLOW_TAG_ENABLED=true
PNL_FLOW_STEP_MIN_USD=5          # ignore dust steps
PNL_FLOW_LOOKBACK_HOURS=24       # detect sudden TOTAL steps vs prior snapshot
```

**Acceptance:**
- [x] `nanodaily` prints: `Flow-adjusted session PnL: $X (+Y%) | detected flows: deposit +$Z @ ts (est)`
- [x] Heuristic v1: sudden TOTAL step up/down with stable/cash leg change → tag as `deposit_est` / `withdraw_est`; log confidence
- [x] Optional manual override file `.runtime/pnl_flow_events.jsonl` (operator tags) merged into report
- [x] Does **not** change trading logic or session baseline automatically
- [x] Unit tests: deposit step, flat market, withdrawal step, below threshold ignored
- [x] `nanoclaw/env_sync.py` preserves new keys

**Do not:** auto-reset session baseline; change swap execution.

**VM verify:**
```bash
nanodaily | grep -E 'Flow-adjusted|detected flows'
```

---

## Agent H — WETH fallback spot refresh (P1) — **DONE**

**Goal:** When live WETH quote diverges materially from cached fallback (`FE_USD FALLBACK FLOOR`), refresh fallback or prefer live quote so TOTAL matches MetaMask and mark PnL is honest.

**Context:** Logs show `live_quote_usdt=$129.70` vs `fallback_px_usd=2022.7890` — TOTAL still OK via fallback total but operator sees scary warnings; mark attribution is wrong.

**Files:** FE USD / valuation module (grep `FALLBACK FLOOR`, `FE_USD`, `last_good_spot`), `modules/swap_executor.py` or dedicated `modules/fe_valuation.py`, tests, `docs/OPERATOR_PNL_MARK_VS_TRADE.md` (one paragraph)

**Env (`.env.example`):**
```bash
FE_USD_FALLBACK_REFRESH_ENABLED=true
FE_USD_FALLBACK_MAX_STALE_PCT=5.0    # refresh when |live-fallback|/live > 5%
FE_USD_FALLBACK_MIN_LIVE_USD=1.0     # skip refresh on dust balances
```

**Acceptance:**
- [x] On cycle: if divergence > threshold, update in-memory fallback from live quote (or always use live when quote succeeds)
- [x] Log: `[nanoclaw] FE_USD FALLBACK REFRESH | sym=WETH_ALPHA | old_px=… | new_px=… | source=live_quote`
- [x] If live quote fails, keep last good fallback (no regression)
- [x] Unit tests: stale fallback refreshed, failed quote keeps fallback, dust skipped
- [x] `nanohealth` TOTAL within ~1% of MetaMask after refresh on stage book fixture

**Do not:** change FE runway / tiered / operating reserve thresholds.

---

## Agent I — STAGE_SEED auto-sync + wallet opex runway alert (P2) — **DONE**

**Goal (A):** Optional auto-update of effective seed for operating reserve from rolling TOTAL so reserve floor scales with book without manual `.env` edits.

**Goal (B):** Telegram (or log) alert when wallet stables approach opex runway (Ankr + hosting + optional Cursor/Grok budgets).

**Files:** `config.py`, `modules/swap_executor.py` (`_operating_reserve_seed_usd`), `external_layer/` or `scripts/opex_runway.py`, `.env.example`, `nanoclaw/env_sync.py`, tests

**Env (`.env.example`):**
```bash
STAGE_SEED_AUTO_SYNC_ENABLED=false   # default off; operator opt-in
STAGE_SEED_AUTO_SYNC_EMA_DAYS=7      # smooth seed from portfolio_history
STAGE_SEED_AUTO_SYNC_MIN_USD=50
OPEX_MONTHLY_USD=10
OPEX_CURSOR_MONTHLY_USD=0
OPEX_GROK_MONTHLY_USD=0
OPEX_HOSTING_MONTHLY_USD=0
OPEX_RUNWAY_ALERT_DAYS=14            # alert when stables < N days of opex at current burn
OPEX_RUNWAY_TELEGRAM_ENABLED=false
```

**Acceptance (A):**
- [x] When `STAGE_SEED_AUTO_SYNC_ENABLED=true`, reserve seed = max(`STAGE_SEED_USD` env, EMA of daily TOTAL closes) capped sensibly
- [x] Log once per day: `[nanoclaw] STAGE_SEED_EMA | seed_usd=… | reserve_floor=…`
- [x] `STAGE_SEED_USD=158` in env still acts as floor minimum when auto-sync on

**Acceptance (B):**
- [x] Script or external-layer tick: if `stables_usd < (sum monthly opex / 30) * OPEX_RUNWAY_ALERT_DAYS`, emit alert
- [x] Message includes wallet `0x05eF…1FBe6`, stables, days runway, line items
- [x] Tests with stub env + mocked Telegram

**Do not:** auto-pull funds from wallet; change green gate floors.

**VM verify:**
```bash
grep STAGE_SEED_EMA real_cron.log | tail -3
python scripts/opex_runway.py --dry-run
```

---

## Agent J — Adverse-day metrics (P3) — **DONE**

**Goal:** Read-only diagnostics answering: “Did high velocity help or hurt?” on red days — **realized trade PnL** vs **mark delta** vs **gas/churn cost**.

**Files:** `scripts/pnl_report.py`, new `scripts/pnl_adverse_day.py` or extend `nanodaily`, trade log parser (grep `EXEC SUCCESS` / receipts if available), `tests/unit/test_pnl_adverse_day.py`, `docs/OPERATOR_PNL_MARK_VS_TRADE.md`

**Env (`.env.example`):**
```bash
PNL_ADVERSE_DAY_ENABLED=true
PNL_ADVERSE_DAY_WINDOW_HOURS=24
PNL_ADVERSE_DAY_MIN_FILLS=3
GAS_USD_EST_PER_FILL=0.05        # v1 manual; v2 from receipts optional
```

**Acceptance:**
- [x] `python scripts/pnl_adverse_day.py` (or `nanodaily --adverse`) prints for last 24h when TOTAL Δ < 0:
  - `mark_delta_usd`, `turnover_usd`, `fill_count`, `gas_est_usd`, `realized_trade_est_usd`, `churn_cost_est_usd`
- [x] `nanodaily` one-liner when window is red: `Adverse window: mark $X | churn est $Y | fills N`
- [x] Uses existing portfolio_history + log scrape; no new on-chain indexer required for v1
- [x] Unit tests with fixture logs (10 fills, flat mark vs dump mark)

**Do not:** change trading parameters based on metrics (read-only v1).

**VM verify:**
```bash
python scripts/pnl_adverse_day.py --hours 24
```

---

## Agent K — On-chain deposit/withdraw tags v2 (P2)

**Goal:** Upgrade flow tags from portfolio_history heuristics to **on-chain tx attribution** (Polygonscan-style): tag USDT/USDC/MATIC transfers in/out of stage wallet as capital flows.

**Context:** Flow-adjusted PnL v1 tagged deposit +$18.67 and withdraw -$10.02 (Ankr) correctly; v2 confirms via tx receipts.

**Files:** `nanoclaw/pnl_flow_onchain.py`, `scripts/pnl_flow_sync.py`, extend `scripts/pnl_report.py`, `.env.example`, tests

**Env:**
```bash
PNL_FLOW_ONCHAIN_ENABLED=true
PNL_FLOW_ONCHAIN_LOOKBACK_HOURS=168
PNL_FLOW_WALLET=0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6
```

**Acceptance:**
- [ ] Scrape wallet ERC20 transfers via RPC logs (USDT/USDC); classify in/out vs bot wallet
- [ ] Merge into `.runtime/pnl_flow_events.jsonl` with tx hash + block time
- [ ] `nanodaily` prefers on-chain tags over heuristic when both present
- [ ] Does not change trading logic or session baseline
- [ ] Tests with fixture log topics / mocked eth_getLogs

**Do not:** auto-move funds; change green gates.

---

## Parent review checklist (before push)

```bash
python -m pytest tests/unit/test_runtime_inventory_mtm.py tests/unit/test_opex_gate.py tests/unit/test_pnl_report.py tests/unit/test_pnl_adverse_day.py tests/unit/test_opex_runway.py tests/unit/test_stage_seed_auto_sync.py -q
python -m pytest tests/unit/test_rpc_probe.py tests/unit/test_operating_reserve.py tests/unit/test_rpc_health.py tests/unit/test_fe_stable_runway_tiered.py -q
python -m pytest tests/unit/test_external_auto_pause.py tests/unit/test_nano_green.py -q
python scripts/rpc_probe.py
python -m compileall -q nanoclaw modules scripts external_layer
```

**VM after push:**
```bash
NANOUP_AUTOSTASH=1 nanodeploy
# Fix Ankr key (operator): ANKR_RPC_KEY in .env → nanohealth ok
STAGE_SEED_USD=158  # stage VM book (~May 2026); reserve floor = 158 × 10% = $15.80
grep OPERATING_RESERVE real_cron.log | tail -5
nano12h
python3 -c "import json; print(json.load(open('control.json')))"
```

Expect: session FAIL → **auto_pause** sets `paused=True` within ~30s; reserve floor defers entries at $8.91 stables.
