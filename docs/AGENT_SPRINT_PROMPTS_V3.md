# Agent sprint prompts — V3 (Jun 2026)

Copy **one prompt per parallel agent**. Parent merges to `V3`, runs the **parent review checklist** at the bottom, then **merge V3 → V2** only after stage VM monitoring is green.

**Do not deploy V3 to stage VM while V2 is live-monitoring** — dev/test locally and in CI only until the pre-deploy gate passes.

| Item | Value |
|------|--------|
| **Dev branch** | `V3` (fork from `V2` @ `02c5fcd7` or later) |
| **Live branch** | `V2` on stage VM — leave running |
| **VM path** | `~/.nanobot/workspace/nanoclaw` |
| **Stage wallet** | `0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6` |
| **Do not commit** | `.env`, keys, `control.json` |

## V2 baseline (already shipped)

- `ed1dc1cb` — tiered reserve headroom + min notional  
- `02c5fcd7` — high-FE de-risk trim (`FE STABLE RUNWAY DERISK`) + attribution USD fix  

**Stage book reference (post-derisk):** ~$154 TOTAL, **75% FE**, **$31 stables**, auto-pause until 12h window > −2%.

---

## Parent — bootstrap V3 (run once)

```
Create branch V3 from origin/V2 at latest (≥ 02c5fcd7).
Do not change trading defaults on V3 beyond what sprint agents specify.
Add docs/AGENT_SPRINT_PROMPTS_V3.md to the branch if missing.
Confirm: python -m pytest tests/unit/test_fe_stable_runway_derisk.py tests/unit/test_fe_stable_runway_tiered.py -q
Output: git log -1 --oneline on V3.
```

---

## Parallel waves (minimize merge conflicts)

| Wave | Agents | Can run together? | Touches |
|------|--------|-------------------|---------|
| **1** | L, M, N, O | ✅ Yes | external_layer, scripts, nano_green only |
| **2** | P, Q, R | ✅ Yes | new `nanoclaw/*` modules + thin hooks |
| **3** | S, T | ⚠️ Pair OK | `modules/swap_executor.py` / `signal.py` — **one owner each** |
| **4** | Parent | After all | merge, full pytest, pre-deploy script |

**Rule:** Agents **P–R** add logic in **new modules** and expose **one public function** wired from existing call sites. Avoid editing the same function bodies in parallel.

---

## Agent L — Tiered re-entry cooldown (P3)

**Goal:** After unpause, rebuild-to-stable, or tiered BUY, block **tiered USDC→EQUITY** for N hours so stables recover before the next capped buy.

**New module:** `nanoclaw/fe_tiered_cooldown.py`  
**Wire:** `modules/swap_executor.py` → `_fe_stable_runway_tiered_bypass_context` returns `None` when cooldown active; set cooldown on successful tiered fill + on WMATIC→stable rebuild fill.

**Env (`.env.example`):**
```bash
FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED=true
FE_STABLE_RUNWAY_TIERED_COOLDOWN_HOURS=4
FE_STABLE_RUNWAY_TIERED_COOLDOWN_AFTER_REBUILD=true
```

**Acceptance:**
- [ ] Log defer: `[nanoclaw] FE STABLE RUNWAY TIERED | cooldown | stable_usd=… | until=…`
- [ ] Cooldown persisted in `.runtime/fe_tiered_cooldown.json` (gitignored)
- [ ] Unit tests: active cooldown blocks; expiry allows; rebuild trigger optional
- [ ] `nanoclaw/env_sync.py` preserves new keys
- [ ] **Do not** weaken reserve headroom or derisk thresholds

**Do not:** change `EXTERNAL_AUTO_*` gates or operating reserve.

---

## Agent M — Auto-unpause hysteresis (P4)

**Goal:** Require 12h window **above** floor for **N consecutive** external-layer ticks before `auto_unpause` (reduces pause/unpause whipsaw).

**New module:** `external_layer/unpause_hysteresis.py`  
**Wire:** `external_layer/auto_pause.py` → `evaluate_auto_pause()`

**Env:**
```bash
EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED=true
EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS=6
EXTERNAL_AUTO_UNPAUSE_WINDOW_BUFFER_PCT=0.25
```
(window must be ≥ `EXTERNAL_AUTO_WINDOW_MIN_PCT + buffer`, e.g. −2% + 0.25 → −1.75%)

**Acceptance:**
- [ ] When enabled, single tick above floor does not unpause
- [ ] Log: `[external] auto_unpause hysteresis | ticks=3/6 | window=-1.9%`
- [ ] Tests in `tests/unit/test_external_auto_pause.py` with mocked tick counter
- [ ] Default **off** or conservative defaults — document in `docs/OPERATOR_PNL_MARK_VS_TRADE.md`

**Do not:** edit swap_executor or signal paths.

---

## Agent N — On-chain flow auto-sync (P8 / finish Agent K)

**Goal:** Cron-friendly flow sync — no manual `python scripts/pnl_flow_sync.py`.

**Files:** `external_layer/pnl_flow_gate.py` (new), wire from `external_layer/control.py` or document cron in `scripts/nanobot_aliases.sh`

**Env:**
```bash
PNL_FLOW_AUTO_SYNC_ENABLED=true
PNL_FLOW_AUTO_SYNC_INTERVAL_HOURS=6
```

**Acceptance:**
- [ ] Reuses `nanoclaw/pnl_flow_onchain.py` + `scripts/pnl_flow_sync.py` logic (no duplicate scraper)
- [ ] Log: `[nanoclaw] PNL_FLOW_SYNC | scraped=N appended=M wallet=0x05eF…`
- [ ] Tests with mocked RPC logs in `tests/unit/test_pnl_flow_onchain.py`
- [ ] `nanodaily` still prefers on-chain tags over heuristic

**Do not:** change session baseline or trading.

---

## Agent O — nano_green runway log freshness (ops)

**Goal:** `nano12h` / `nanogreen` “last 3 FE STABLE RUNWAY” lines include **timestamps** and exclude pre-deploy lines older than window (fixes stale `TIERED allow` confusion).

**Files:** `scripts/nano_green.py` (or module it calls), `tests/unit/test_nano_green.py`

**Acceptance:**
- [ ] Runway grep scoped to last **12h** of `real_cron.log` (or configurable)
- [ ] Each runway line prefixed with log timestamp when available
- [ ] Unit test with fixture log containing old tiered + new defer lines
- [ ] No trading logic changes

---

## Agent P — Dynamic FE trim bands (P5)

**Goal:** When `fe_share > 85%`, allow **smaller / more frequent** derisk caps; when `fe_share < 70%`, skip derisk. Scales `FE_STABLE_RUNWAY_DERISK_MAX_TRIM_NOTIONAL_USD`.

**New module:** `nanoclaw/fe_dynamic_trim.py`  
**Wire:** `modules/swap_executor.py` → `_fe_stable_runway_derisk_context` reads effective max trim + min fe share from module.

**Env:**
```bash
FE_STABLE_RUNWAY_DERISK_DYNAMIC_ENABLED=true
FE_STABLE_RUNWAY_DERISK_HIGH_FE_SHARE=0.85
FE_STABLE_RUNWAY_DERISK_HIGH_FE_MAX_TRIM_USD=15
FE_STABLE_RUNWAY_DERISK_LOW_FE_SHARE=0.70
```

**Acceptance:**
- [ ] At 87% FE → max trim $15; at 72% FE → derisk off; at 75% FE → default $12
- [ ] Log includes `dynamic_trim_usd=…`
- [ ] Tests in `tests/unit/test_fe_dynamic_trim.py`
- [ ] **Do not** change dead-zone stable bounds ($15–$40) without tests

---

## Agent Q — Drawdown notional throttle (P7)

**Goal:** When 8h window PnL < −1%, halve tiered max notional and X-SIGNAL buy multiplier for new entries.

**New module:** `nanoclaw/drawdown_throttle.py`  
**Wire:** `modules/swap_executor.py` → `fe_stable_runway_tiered_cap_notional_usd`; optional hook in `signal.py` buy sizing.

**Env:**
```bash
DRAWDOWN_THROTTLE_ENABLED=true
DRAWDOWN_THROTTLE_WINDOW_HOURS=8
DRAWDOWN_THROTTLE_TRIGGER_PCT=-1.0
DRAWDOWN_THROTTLE_NOTIONAL_MULT=0.5
```

**Acceptance:**
- [ ] Uses same window math as `scripts/nano_green.py` / portfolio_history
- [ ] Log: `[nanoclaw] DRAWDOWN THROTTLE | window=-1.2% | tiered_max=$5.00`
- [ ] Protection exits (derisk, rebuild, loss-cut) **exempt**
- [ ] Tests with fixture portfolio_history CSV

**Do not:** change pause floors (`EXTERNAL_AUTO_WINDOW_MIN_PCT`).

---

## Agent R — Adverse-day → churn guard (P9)

**Goal:** Read-only adverse metrics **optionally** emit a **soft cap** recommendation consumed by Q (or log-only v1): when 24h red + fills ≥ min, log `ADVERSE CHURN GUARD` and set runtime flag for throttle.

**New module:** `nanoclaw/adverse_churn_guard.py`  
**Wire:** called from `scripts/pnl_report.py` `_print_adverse_day_oneliner` or start of swap cycle (log-only v1).

**Env:**
```bash
ADVERSE_CHURN_GUARD_ENABLED=true
ADVERSE_CHURN_GUARD_FILL_MULT=0.5
```

**Acceptance:**
- [ ] Builds on `nanoclaw/pnl_adverse_day.py` — no duplicate parsers
- [ ] v1: **log + `.runtime/adverse_churn_flag.json`** only; no forced trades
- [ ] v2 hook documented for Agent Q to read flag (optional same sprint if sequential)
- [ ] Tests in `tests/unit/test_adverse_churn_guard.py`

**Do not:** auto-pause or change green gates in v1.

---

## Agent S — WMATIC idle rotation at high stables (P6)

**Goal:** When stables **≥ $30**, WMATIC signal **≥ 0.85**, `fe_share < 80%`, and idle cycles met → allow **capped USDC→WMATIC** (rotation alpha) without full runway target.

**Files:** `modules/swap_executor.py` (main strategy / rotation section only), `config.py`, tests

**Env:**
```bash
MAIN_STRATEGY_HIGH_STABLE_WMATIC_ROTATION_ENABLED=true
MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_STABLE_USD=30
MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_NOTIONAL_USD=10
MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_SIGNAL=0.85
MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_FE_SHARE=0.80
```

**Acceptance:**
- [ ] Blocked when operating reserve or drawdown throttle active
- [ ] Blocked when tiered cooldown active (coordinate with Agent L via shared helper or document order)
- [ ] Log: `[nanoclaw] HIGH STABLE WMATIC ROTATION | stable_usd=… | signal=… | max_notional=$10`
- [ ] Tests: eligible at $31 stables / 75% FE; blocked at 83% FE
- [ ] Respects `control.json` pause for **entries**

**Do not:** run in same PR as Agent P (both touch derisk/fe bands) — merge P before S or rebase.

---

## Agent T — Pre-deploy verification script (gate)

**Goal:** One command to run **before** merging V3 → V2 and `nanodeploy`.

**New file:** `scripts/v3_pre_deploy_check.sh` + `tests/unit/test_v3_pre_deploy_check.py` (optional)

**Acceptance:**
- [ ] Runs: targeted pytest list, `python -m compileall`, `python scripts/unpause_readiness.py`, dry `nano_green` with fixture log
- [ ] Prints checklist: git head, env keys present, no `TIERED allow` regression tests pass
- [ ] Document in `docs/DEV_WORKFLOW.md` § V3 merge gate
- [ ] Exit non-zero on any failure

---

## Parent review checklist (V3, before merge to V2)

```bash
git checkout V3 && git pull
python -m pytest tests/unit/test_fe_stable_runway_tiered.py tests/unit/test_fe_stable_runway_derisk.py -q
python -m pytest tests/unit/test_external_auto_pause.py tests/unit/test_nano_green.py -q
python -m pytest tests/unit/test_pnl_report.py tests/unit/test_pnl_adverse_day.py tests/unit/test_pnl_flow_onchain.py -q
# After agents land:
python -m pytest tests/unit/test_fe_tiered_cooldown.py tests/unit/test_fe_dynamic_trim.py tests/unit/test_drawdown_throttle.py -q
python -m pytest tests/unit/test_adverse_churn_guard.py -q
python -m compileall -q nanoclaw modules scripts external_layer
bash scripts/v3_pre_deploy_check.sh
```

**Merge gate (stage VM still on V2):**
1. V2 monitoring: `nano12h` window PASS + `paused=False` stable for ≥4h **OR** operator accepts risk  
2. Merge `V3` → `V2`, push, `NANOUP_AUTOSTASH=1 nanodeploy`  
3. Verify: `git log -1`, `grep DERISK`, `nano12h`, no ping-pong `TIERED` at stables < $23  

---

## Copy-paste prompts for Cursor agents (wave 1 — fully parallel)

### Prompt L (P3 cooldown)
```
Branch: V3 (create from origin/V2 if needed). Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent L.

Implement tiered re-entry cooldown in NEW file nanoclaw/fe_tiered_cooldown.py; thin wire in modules/swap_executor.py _fe_stable_runway_tiered_bypass_context only.

Add config keys, .env.example, env_sync, tests/unit/test_fe_tiered_cooldown.py.
Do not deploy; do not change EXTERNAL_AUTO_* or derisk/headroom logic.
Run targeted pytest before done.
```

### Prompt M (P4 hysteresis)
```
Branch: V3. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent M.

Implement auto-unpause hysteresis in external_layer/unpause_hysteresis.py; wire external_layer/auto_pause.py.
Defaults conservative (enabled=false ok). Tests in test_external_auto_pause.py.
No swap_executor changes.
```

### Prompt N (P8 flow sync)
```
Branch: V3. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent N.

Add PNL_FLOW_AUTO_SYNC to external layer (6h interval), reusing pnl_flow_onchain + pnl_flow_sync.
Tests with mocked RPC. Update .env.example + env_sync.
No trading changes.
```

### Prompt O (nano_green freshness)
```
Branch: V3. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent O.

Fix nano_green runway tail to filter last 12h and show timestamps. Tests with fixture real_cron.log excerpt.
No trading logic changes.
```

---

## Copy-paste prompts (wave 2 — parallel)

### Prompt P (P5 dynamic trim)
```
Branch: V3. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent P.

Implement nanoclaw/fe_dynamic_trim.py; wire into _fe_stable_runway_derisk_context max_trim only.
Tests + .env.example. Do not edit tiered headroom.
```

### Prompt Q (P7 drawdown throttle)
```
Branch: V3. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent Q.

Implement nanoclaw/drawdown_throttle.py; wire fe_stable_runway_tiered_cap_notional_usd.
Protection exits exempt. Tests with portfolio_history fixture.
```

### Prompt R (P9 adverse churn)
```
Branch: V3. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent R.

Implement nanoclaw/adverse_churn_guard.py — log-only v1 + .runtime flag for future throttle.
Wire from pnl_adverse_day path. Tests only; no auto-pause.
```

---

## Copy-paste prompts (wave 3 — sequential preferred)

### Prompt S (P6 WMATIC rotation) — after L + Q merged
```
Branch: V3 rebased on latest. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent S.

High-stable WMATIC rotation when stables≥$30, fe_share<80%, signal≥0.85.
Respect pause, tiered cooldown, drawdown throttle. Main strategy section + tests.
```

### Prompt T (pre-deploy gate) — anytime
```
Branch: V3. Read docs/AGENT_SPRINT_PROMPTS_V3.md Agent T.

Add scripts/v3_pre_deploy_check.sh and DEV_WORKFLOW.md merge gate section.
```

---

## Expected impact (rotation & PnL) — full V3 bundle

| Agent | Rotation | PnL / risk |
|-------|----------|------------|
| L cooldown | ↓ tiered churn on resume | Less ping-pong relapse |
| M hysteresis | None while paused | Fewer whipsaw unpauses |
| N flow sync | None | Honest session PnL |
| O nano_green | None | Ops clarity only |
| P dynamic trim | ↑ defensive sells when FE>85% | Lower mark beta |
| Q throttle | ↓ entry size in drawdown | Smaller losses near pause band |
| R adverse guard | ↓ optional cap when churn+red | Cuts gas bleed on bad days |
| S WMATIC rotation | ↑ alpha entries when stables high | Upside capture post-derisk |
| T gate | None | Safe merge |

**Realistic pace to ~$160 after V3 deploy:** not a single +10% day — expect **+$4–8 over 1–2 weeks** with ETH flat if rotation + throttle work; **+10% day** still requires market luck + aggressive entries (Agent S).

---

## What stays on V2 VM meanwhile

- Monitor: `nano12h | grep window,control,fe_share`  
- **No V3 deploy** until parent merge gate  
- WETH JSON floor **2000** stays operator-local on VM  
