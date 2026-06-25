# Session PnL: mark-to-market vs realized trades

Operators sometimes see **Session PnL** drop with **zero swaps** in the session window. That is often **mark-to-market (MTM)** on followed-equity inventory (`FE_USD`), not a bad fill. This doc explains how to tell the difference and when to reset the session baseline.

**Related:** `AI_CONTEXT.md` (what `TOTAL` / `FE_USD` include), `docs/readme-vm-update.md` (`nanopnl`, `nanodaily`), `.env.example` (`FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY`).

---

## What Session PnL measures

`nanopnl` / `nanodaily` compute:

```
Session PnL = current TOTAL − session_start_total
```

- **`session_start_total`** lives in `portfolio_session_baseline.json` (created on first run or after `nanopnl --reset-session`).
- **`TOTAL`** is the bot’s Polygon-only wallet mark: stables + WMATIC×price + POL×`POL_USD_PRICE` + **`FE_USD`**.

Session PnL is **not** “realized PnL from trades only.” Any component of `TOTAL` can move without a swap:

| Component | Can move without a trade? |
|-----------|---------------------------|
| USDT / USDC | Deposits, withdrawals, gas spend |
| WMATIC / POL | Price marks, unwrap/wrap (logged) |
| **FE_USD** | **Spot cache / live quote / fallback floor** |

Check **velocity** lines in the report (`velocity_fills_session`, turnover) before blaming strategy.

---

## Stage velocity commits (May–Jun 2026)

| Tag | Commit | What it did |
|-----|--------|-------------|
| **abc** | `61adb81b` | Tiered FE runway — **$140→~$160** velocity day (10 fills, capped $10); deposit + rotation |
| **abc+ops** | `9d171080` | Flow-adjusted PnL, opex runway script, adverse-day metrics (no trading change) |
| **abc+auto** | `e06cd360` | WETH fallback refresh, seed EMA auto-sync, opex auto-check in external layer |
| **abc+velocity2** | (latest) | Reserve tiered exempt + low-stables rebuild fix (unblocks flat ~$158 book) |

After **abc**, stables fell below **10% reserve** (~$15.80 on $158 seed) → tiered buys and WMATIC→stable rebuild both stalled until velocity2.

**Jun 2026 fix:** When stables **< $15** rebuild threshold, **no tiered BUY** (rebuild only). WMATIC→USDC dust bypass floor lowered to **$4** so ~$4.90 reserve-protection sells execute.

**Jun 2026 headroom:** Tiered BUY capped so post-trade stables stay **≥ reserve floor + `FE_STABLE_RUNWAY_TIERED_RESERVE_HEADROOM_USD`** (default **$2**). At ~**$19** stables (after rebuild), tiered is **blocked** (would need **≥ ~$22.80** for a **$5** min buy). Stops rebuild→**$10** tiered→**~$9** ping-pong churn.

**Jun 2026 tiered re-entry cooldown:** After a successful **tiered USDC→EQUITY** fill or **WMATIC→stable rebuild** (`FE_STABLE_RUNWAY_TIERED_COOLDOWN_AFTER_REBUILD=true`), tiered BUY is blocked for **`FE_STABLE_RUNWAY_TIERED_COOLDOWN_HOURS`** (default **4h**). State: **`.runtime/fe_tiered_cooldown.json`**. Log: `[nanoclaw] FE STABLE RUNWAY TIERED | cooldown | stable_usd=… | until=…`.

**Jun 2026 handoff:** Full thread state — [`docs/OPERATOR_HANDOFF_2026-06-01.md`](OPERATOR_HANDOFF_2026-06-01.md) (VM on `V2` @ `02c5fcd7`, V3 @ `de1c1c24` not deployed).

**Jun 2026 de-risk:** When `fe_share ≥ 80%`, stables **$15–$40**, and WMATIC **&lt; $8** (rebuild exhausted), bot may run **capped ~$12 WETH→USDC** (`FE STABLE RUNWAY DERISK`) — works while auto-paused. Lowers ETH mark beta without tiered BUY churn.

**Jun 2026 window-stress de-risk (optional, default off):** When `WINDOW_STRESS_DERISK_ENABLED=true` and external layer paused **only** for `auto_pause | window PnL below …` (12h floor, default **−2%** — unchanged), DERISK may use relaxed gates: **`WINDOW_STRESS_DERISK_MIN_FE_SHARE`** (default **0.72**) and **`WINDOW_STRESS_DERISK_MAX_WMATIC_USD`** (default **$12**). Still capped `FE_STABLE_RUNWAY_DERISK_MAX_TRIM_NOTIONAL_USD`; **entries and tiered BUY stay blocked**; tiered cooldown unchanged.

**Jun 2026 auto-unpause hysteresis (optional, default off):** When `EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED=true`, the external layer (~30s ticks) requires **N consecutive** ticks where the **12h window PnL** is at least **`EXTERNAL_AUTO_WINDOW_MIN_PCT + EXTERNAL_AUTO_UNPAUSE_WINDOW_BUFFER_PCT`** (defaults: −2% + 0.25 → **−1.75%**) before writing `auto_unpause` to `control.json`. A single tick above the −2% pause floor is not enough — reduces pause/unpause whipsaw when the window hovers near the floor. Log example: `[external] auto_unpause hysteresis | ticks=3/6 | window=-1.9%`. Env: `EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS` (default **6**). See `external_layer/unpause_hysteresis.py`.

**Jun 2026 pause_exec discipline (always on):** `nano_green` / `EXTERNAL_AUTO_PAUSE_ENABLED` treat **`pause_exec`** as **FAIL** when **`real_cron.log`** shows **`EXEC SUCCESS`** in the **active paused window** — from the last **`[CONTROL] paused=True`** until the first **`auto_unpause`** clearance (`[CONTROL] paused=False` or **`External layer reason: auto_unpause`**). Fills **after** a cleared unpause do not fail the gate. Re-pause with **`fill while paused (discipline breach)`** still counts fills after the brief unpause in that episode. Complements dual-window unpause; does **not** change **`EXTERNAL_AUTO_WINDOW_MIN_PCT`** (−2%) or tiered cooldown.

---

## `FE_USD` and `FE_USD AUTO_FLOOR_UPDATE`

**`FE_USD`** is the USDT-notional value of tokens listed in `followed_equities.json` (e.g. Polygon WETH `0x7ceB…`, LINK, WBTC). The runtime quotes each balance via Uniswap paths and applies a **floor** so drained pools do not silently undercount inventory.

**Effective floor per symbol:**

```
effective_floor_px = min(current_price_usd in JSON, last_good_spot from cache)
per-asset USD      = max(live_quote_usdt, balance × effective_floor_px)
```

When a **healthy live quote** confirms value at or above that floor, the bot may persist a new **`last_good_spot_usd`** per symbol in **`.runtime/fe_usd_spot_cache.json`** (gitignored on dev machines; lives on the VM). Upward drift is capped by **`FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY`** (default **5%** / day in `.env.example`).

When the cache spot changes, `real_cron.log` emits:

```
[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2022.0000 | json_floor=2500.0000 | effective_floor=2022.0000
```

**What this means for operators:**

- The bot **re-anchored** the MTM floor to a fresh live spot (here **2022** USD/token), not necessarily a trade loss.
- Stale **`current_price_usd`** in JSON (e.g. **2500**) no longer overstates `TOTAL` when cache or live data is fresher.
- A **downward** cache update (2500 → 2022) lowers **`FE_USD`** and **`TOTAL`** even if **no swap** ran—Session PnL reflects that mark.

**Other FE log lines:**

| Line | Meaning |
|------|---------|
| `FE_USD FALLBACK FLOOR APPLIED` | Live quote below floor; floor won for this cycle |
| `FE_USD UNQUOTED` | No live quote and no usable floor; position may contribute $0 |

Grep on VM:

```bash
grep -E 'FE_USD AUTO_FLOOR_UPDATE|FE_USD FALLBACK|FE_USD UNQUOTED' real_cron.log | tail -30
```

---

## Example: TOTAL $132 → $122 with MetaMask aligned (31 May 2026)

Observed pattern:

- Session PnL **−$10** with **no session fills**.
- MetaMask **Polygon tab** total moved in the same direction as bot **`TOTAL`**.
- Log showed **`FE_USD AUTO_FLOOR_UPDATE | last_good_spot=2022`** (WETH spot cache stepped down from a stale JSON floor).

**Interpretation:** MTM honesty pass on followed equity—not evidence of a silent bad trade. Cross-check Polygon token balances on [Polygonscan](https://polygonscan.com/) for `WALLET=`; quantities should be unchanged if it was mark-only.

`nanopnl` may print a read-only hint when the spot cache moved **>1%** since session start:

```
mark_delta_est: $-10.00 (FE spot cache)
```

That line is an **estimate** from `FE_USD` at session start vs now (log + cache). It does not change trading or baselines.

---

## Capital flows vs trade PnL (flow-adjusted session line)

When you **deposit or withdraw** stables, raw **Session PnL** includes that capital movement. A +$18 USDT top-up can make session % look like “alpha” even when marks and trades were flat.

With **`PNL_FLOW_TAG_ENABLED=true`** (default), `nanodaily` / `nanopnl` print:

```
Flow-adjusted session PnL: $+2.50 (+2.1%) | detected flows: deposit +$18.00 @ 2026-05-31T10:00:00+00:00 (est)
```

**Heuristic v1** scans `portfolio_history.csv` for sudden **TOTAL** steps where **USDT+USDC** moved in the same direction and explains most of the step (`PNL_FLOW_STEP_MIN_USD`, default **$5**; lookback **`PNL_FLOW_LOOKBACK_HOURS`**, default **24**). WETH rotation (stables down, `FE_USD` up) should **not** tag as a deposit.

**Manual overrides:** append JSON lines to **`.runtime/pnl_flow_events.jsonl`**:

```json
{"timestamp": "2026-05-31T12:00:00+00:00", "kind": "deposit", "amount_usd": 18.0, "note": "USDT top-up"}
```

Flow tagging is **read-only** — it does **not** reset `portfolio_session_baseline.json` or change swap execution.

**On-chain v2:** with **`PNL_FLOW_ONCHAIN_ENABLED=true`**, flows sync via **`PNL_FLOW_AUTO_SYNC_ENABLED=true`** (external layer, default every **6h**) or manual/cron **`python scripts/pnl_flow_sync.py`**. Both scrape Polygon **USDT/USDC Transfer** logs for **`PNL_FLOW_WALLET`** via RPC and append tx-attributed rows to **`.runtime/pnl_flow_events.jsonl`**. `nanodaily` **prefers on-chain tags over heuristic** when both detect the same flow. Env: **`PNL_FLOW_ONCHAIN_LOOKBACK_HOURS`** (default **168**), **`PNL_FLOW_AUTO_SYNC_INTERVAL_HOURS`** (default **6**).

---

## MetaMask parity — what matches and what does not

The bot is **Polygon PoS only** (chain **137**). **`TOTAL`** is **not** promised to equal MetaMask’s **all-network** headline.

| Compare this | To this |
|--------------|---------|
| MetaMask **Polygon** network selected | Bot `WALLET TOTAL USD` / `nanopnl` **TOTAL** |
| Polygon WETH contract **`0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619`** | `FE_USD` / `followed_equities.json` |
| USDC.e + native USDC + USDT on Polygon | `STABLE_USD` in logs |

**Common mismatches (not bugs):**

- **Ethereum mainnet WETH** (`0xC02a…`) — **out of scope** for v2.8 `TOTAL`; bridge to Polygon or book manually.
- MetaMask **“All popular networks”** — aggregates chains the bot ignores.
- **WMATIC** in logs is **quantity**; USD uses the bot’s live WMATIC price (may differ slightly from MetaMask’s mark).
- **RPC read suspect** warning in `nanopnl` — near-zero stables with large `TOTAL`; fix RPC before trusting PnL (`nanohealth`).

When Session PnL and MetaMask **Polygon tab** move together after `AUTO_FLOOR_UPDATE`, trust the **shared MTM story** over “we must have traded.”

---

## Mark vs trade — quick checklist

1. **`nanohealth`** — RPC green?
2. **`nanopnl`** — read **velocity_fills_session** and **turnover**; zero fills ⇒ no realized swap PnL in window.
3. **`grep FE_USD`** — `AUTO_FLOOR_UPDATE`, `FALLBACK`, `UNQUOTED`?
4. **Polygonscan** — token **balances** unchanged vs **USD** marks moved?
5. **MetaMask** — **Polygon network only**, same contracts as `followed_equities.json`.

If marks explain the delta, **do not** pause trading solely for Session PnL unless risk policy says otherwise.

---

## When to `nanopnl --reset-session` (rare)

Reset **only** when the session baseline no longer matches the story you want to track—not to “hide” MTM moves.

**Good reasons:**

- After a **deploy / config change** where you want PnL from “now” forward.
- After a **deposit or withdrawal** you intentionally exclude from performance view (optional; see flow tagging below).
- You previously reset at a bad RPC snapshot and want a clean anchor after **`nanohealth`** is green.

**Usually wrong reasons:**

- Session PnL dropped because **`FE_USD AUTO_FLOOR_UPDATE`** corrected an **overstated** mark (you would erase honest MTM).
- MetaMask all-network total differs from bot Polygon `TOTAL` (reset does not fix scope).
- “Make the number green again” without a structural baseline change.

Command (also via `nanostatus --reset-session` / `nanorestart --reset-session`):

```bash
nanopnl --reset-session
```

This writes current `TOTAL` into `portfolio_session_baseline.json` and sets `session_started_at` to now (UTC).

---

## Adverse-day window (churn vs mark on red days)

When **TOTAL** drops over the last **24h** (configurable), high fill velocity may be **mark pain** (FE spot) or **churn cost** (gas + turnover friction), not a single bad trade.

With **`PNL_ADVERSE_DAY_ENABLED=true`**, `nanodaily` prints a one-liner when the window is red and fills ≥ **`PNL_ADVERSE_DAY_MIN_FILLS`** (default **3**):

```
Adverse window: mark $-8.00 | churn est $0.61 | fills 10
```

Full breakdown:

```bash
python scripts/pnl_adverse_day.py --hours 24
# or: python scripts/pnl_report.py --adverse-day
```

| Field | Meaning (v1) |
|-------|----------------|
| `mark_delta_usd` | `FE_USD` at window end − start (log scrape) |
| `turnover_usd` | Sum of on-chain `TRADE_ATTRIBUTION` notionals in window |
| `fill_count` | `EXEC SUCCESS` lines in window |
| `gas_est_usd` | `fill_count × GAS_USD_EST_PER_FILL` (default **$0.05**) |
| `churn_cost_est_usd` | Gas est + **10 bps** of turnover (slippage proxy) |
| `realized_trade_est_usd` | `total Δ − mark_delta + churn_cost` (residual) |

**Read-only** — metrics do not change swap sizing, gates, or baselines.

### Adverse churn guard (v1 log + flag)

With **`ADVERSE_CHURN_GUARD_ENABLED=true`**, the same adverse window that prints the one-liner also:

1. Logs **`[nanoclaw] ADVERSE CHURN GUARD | …`** when **24h red** and fills ≥ **`PNL_ADVERSE_DAY_MIN_FILLS`**
2. Writes **`.runtime/adverse_churn_flag.json`** with `"active": true` and **`recommended_notional_mult`** from **`ADVERSE_CHURN_GUARD_FILL_MULT`** (default **0.5**)

When the window is green or fills are below the floor, the flag is refreshed with `"active": false`.

**v1 does not** auto-pause, change green gates, or force trades — log and runtime file only.

**v2 hook (Agent Q):** `nanoclaw.adverse_churn_guard.read_recommended_notional_mult()` returns the recommended multiplier when active (else `1.0`). Intended for tiered max notional / X-SIGNAL buy sizing alongside drawdown throttle — not wired in v1.

```bash
cat .runtime/adverse_churn_flag.json
grep 'ADVERSE CHURN GUARD' real_cron.log | tail -5
```

---

## Auto-pause, mark bleed, and DERISK logs without EXEC

### Mark bleed vs churn (window −2% pause)

When **`EXTERNAL_AUTO_PAUSE_ENABLED=true`**, the external layer (~30s) sets `control.json` **`paused=true`** if any green gate fails. The common stage pattern:

```
auto_pause | window PnL below -2.0% over 12h
```

That means **12h window TOTAL** (from `portfolio_history.csv`) is below the **−2% floor** — **not** necessarily bad fills. Cross-check before calling it churn:

| Signal | Mark bleed | Churn |
|--------|------------|-------|
| `velocity_fills_session` / window fills | **0** or very low | ≥ **`PNL_ADVERSE_DAY_MIN_FILLS`** |
| `FE_USD AUTO_FLOOR_UPDATE` / spot cache | Yes — MTM step on WETH/LINK | Unlikely alone |
| `EXEC SUCCESS` after pause marker | **None** (discipline OK) | Fills while paused → `fill while paused` reason |
| `TIERED \| cooldown` | Often absent | Ping-pong rebuild→tiered loop |
| `Adverse window: mark $… \| churn est $…` | Large **mark** term | Large **turnover** + gas est |

**Operator rule:** Window pause + **no EXEC SUCCESS** + **no tiered cooldown** + red window with **low fills** → treat as **mark bleed**, not strategy churn. Do **not** lower `EXTERNAL_AUTO_WINDOW_MIN_PCT` or disable tiered cooldown to “fix” MTM.

Protection exits (**DERISK**, WMATIC→stable rebuild, loss-cut where allowed) **still run** while paused — only **entries** (X-SIGNAL BUY, tiered, copy) are blocked.

### Why DERISK logs appear without `EXEC SUCCESS`

DERISK has **two log stages** before on-chain execution. `nanogreen` runway tail labels them **`[evaluate]`** vs **`[exec-plan]`**:

| Stage | Log pattern | Meaning |
|-------|-------------|---------|
| **Evaluate** | `FE STABLE RUNWAY DERISK \| evaluate \| fe_share=… \| dynamic_trim_usd=…` | Dynamic trim band resolved (`fe_dynamic_trim.py`). Fires even when later gates block the trim. |
| **Exec plan** | `FE STABLE RUNWAY DERISK \| exec plan \| sym=… \| sell_fraction=…` | Swap **queued** — passed book gates, picked largest FE holding, built plan. Still not on-chain. |
| **On-chain** | `EXEC SUCCESS` (+ `TRADE_ATTRIBUTION`) | Fill confirmed. |

**Common evaluate-only cases (no exec plan, no EXEC SUCCESS):**

1. **`fe_share` below static min** (`FE_STABLE_RUNWAY_DERISK_MIN_FE_SHARE=0.80`) — e.g. **~74% FE** with dynamic `dynamic_trim_usd=12` logged but context returns `None`.
2. **WMATIC USD ≥ `FE_STABLE_RUNWAY_DERISK_MAX_WMATIC_USD`** (default **$8**) — rebuild still actionable; derisk deferred. Example: WMATIC **~$10**, stables **~$26** flat.
3. **Stables outside dead zone** — below **$15** (critical TRIM path) or at/above **$40** target (no FE-heavy block).
4. **Post-plan blocks** — per-asset cooldown, `below_min_net_edge`, dust defer, swap failure.

**Optional relief:** Enable **`WINDOW_STRESS_DERISK_ENABLED=true`** when paused **only** for window PnL — relaxes to FE **≥ 72%** and WMATIC **≤ $12** for capped trim; does **not** change **−2%** unpause floor or tiered cooldown.

Grep on VM:

```bash
grep -E 'FE STABLE RUNWAY DERISK|EXEC SUCCESS|auto_pause|auto_unpause|TIERED \| cooldown' real_cron.log | tail -30
nanogreen   # runway tail shows [evaluate] vs [exec-plan]
```

### Operator checklist — window pause + DERISK evaluate only

1. **`nanogreen`** — confirm `window: FAIL` and reason `auto_pause | window PnL below -2.0% over 12h`; check runway **`[evaluate]`** without matching **`[exec-plan]`** or **`EXEC SUCCESS`**.
2. **`nanopnl`** — `velocity_fills_session` and adverse one-liner; prefer **mark** over **churn** when fills low.
3. **Book shape** — `fe_share`, `STABLE_USD`, WMATIC USD vs `DERISK_MIN_FE_SHARE` / `DERISK_MAX_WMATIC_USD`.
4. **Tiered state** — `grep 'TIERED | cooldown' real_cron.log`; read `.runtime/fe_tiered_cooldown.json` if present.
5. **Window-stress option** — if mark bleed + FE **72–80%** + WMATIC **$8–12**, set `WINDOW_STRESS_DERISK_ENABLED=true` (requires window-only pause); redeploy; expect **`[exec-plan]`** then **`EXEC SUCCESS`** on next qualifying cycle.
6. **Do not** weaken `EXTERNAL_AUTO_WINDOW_MIN_PCT` or `FE_STABLE_RUNWAY_TIERED_COOLDOWN_*` for MTM-only red windows.

---

## Commands reference

```bash
nanohealth                    # RPC before trusting PnL
nanopnl                       # full report (+ mark_delta_est when applicable)
nanodaily                     # compact daily summary (+ adverse one-liner when red)
python scripts/pnl_adverse_day.py --hours 24
grep 'WALLET TOTAL USD' real_cron.log | tail -5
grep 'FE_USD AUTO_FLOOR' real_cron.log | tail -10
cat .runtime/fe_usd_spot_cache.json   # VM only; spot cache per symbol
```
