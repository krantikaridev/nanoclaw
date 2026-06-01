# Operator handoff — 2026-06-01 (stage VM + V3 sprint)

Thread summary for resuming after break. **Live stage VM stays on `V2`** until merge gate passes.

---

## Wallets & paths

| Item | Value |
|------|--------|
| **Stage wallet** | `0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6` |
| **VM path** | `~/.nanobot/workspace/nanoclaw` |
| **Live branch (VM)** | `V2` @ **`02c5fcd7`** (as of last deploy) |
| **Dev branch** | `V3` @ **`de1c1c24`** (not deployed to VM) |
| **Seed / reserve** | `STAGE_SEED_USD=158` → reserve floor **~$15.80** (10%) |

---

## What happened (timeline)

### Problem (May 31 – Jun 1)

- Book peaked ~**$158–160** after deposit + rotation (not pure alpha).
- **Ping-pong churn:** rebuild → **$19 stables** → tiered **$10 BUY** → **~$9 stables** → repeat (~10–11 fills/day, flat/down TOTAL).
- **83% WETH** → window PnL dominated by **ETH mark**, not bad trades.
- Auto-pause triggered at **12h window ≤ −2%**.

### Fixes shipped to **V2** (deployed on VM)

| Commit | Feature |
|--------|---------|
| `ed1dc1cb` | Tiered **reserve headroom** — blocks tiered BUY when post-buy stables would fall below reserve + $2; min tiered **$5** |
| `02c5fcd7` | **FE STABLE RUNWAY DERISK** — capped ~**$12 WETH→USDC** in dead zone ($15–$40 stables, WMATIC dust); works while paused |
| `02c5fcd7` | Attribution **USD** fix (`sz≈12` not `5e19` wei) |
| `e0593a32` | *(V3 only, not on VM yet)* Wave 1: tiered **cooldown**, unpause **hysteresis** (default off), **PNL flow auto-sync**, **nano_green runway timestamps** |

### Post-derisk book (Jun 1 ~11:07 UTC deploy)

One **DERISK** fill on first `02c5fcd7` cycle:

- Stables **$19 → ~$31**
- FE share **83% → ~75%**
- Operator set **WETH JSON floor 2000** in `followed_equities.json` (was 2500)

---

## V3 sprint (dev only — **not on VM**)

All on **`origin/V3`** @ **`de1c1c24`**. See [`AGENT_SPRINT_PROMPTS_V3.md`](AGENT_SPRINT_PROMPTS_V3.md).

| Wave | Agents | Status | Summary |
|------|--------|--------|---------|
| 1 | L, M, N, O | ✅ Done | Tiered cooldown 4h; unpause hysteresis (off); flow sync 6h; runway log timestamps |
| 2 | P, Q, R | ✅ Done | Dynamic FE trim bands; drawdown throttle; adverse churn guard + flag |
| 3 | S, T | ✅ Done | High-stable **USDC→WMATIC** rotation; `scripts/v3_pre_deploy_check.sh` |

**Do not `nanodeploy` V3** until merge gate below.

---

## VM state at break (~12:34 UTC Jun 1)

From operator `nano8h`:

| Metric | Value | Note |
|--------|-------|------|
| **control** | `paused=True` | Reason: **12h window** still below −2% (not 8h) |
| **8h window** | **PASS** −1.19% | Recovered (was −2.7% earlier) |
| **12h window** | Likely still **FAIL** (~−2.5%) | Drives auto-pause |
| **Session PnL** | **+16.6%** | Well above −1% floor |
| **TOTAL (bot)** | ~**$154.21** | MetaMask ~**$157** (mark/methodology gap normal) |
| **Stables** | ~**$31** | Post-derisk target band |
| **FE share** | **75.3%** | Down from 83% |
| **Fills today** | ~12 | Flat since pause (~06:27 UTC) |
| **git on VM** | **`02c5fcd7`** | V3 not pulled |

**Runway grep confusion:** `TIERED | allow` at $31.26 is **expected** (headroom allows $10 at $31 stables). Lines lack timestamps on VM until **V3 Agent O** is deployed. **No new EXEC SUCCESS** while paused = discipline OK.

**Transient RPC 401** on `nano8h` — Ankr key URL failed once; bot uses fallbacks. Check if persistent: `python scripts/rpc_probe.py`, `nanohealth`.

---

## Operator actions taken this session

```bash
# Deploy headroom + derisk
NANOUP_AUTOSTASH=1 nanodeploy   # → 02c5fcd7

# WETH floor (operator-local, do not commit)
python3 - <<'PY' ... current_price_usd=2000 for WETH_ALPHA ...

# Stash VM script noise; pull V2
git stash push -m "vm-local-scripts" -- scripts/
git fetch && NANOUP_AUTOSTASH=1 nanodeploy
```

---

## What to do when you return

### 1. Monitor (no code required)

```bash
nano12h | grep -E 'window|control|fe_share'
nanohealth | grep -E 'Stables|TOTAL|velocity'
grep -E 'auto_unpause|DERISK|TIERED|EXEC SUCCESS|CONTROL.*paused' real_cron.log | tail -20
```

**Unpause signal:** `control: paused=False` with reason `auto_unpause | …` — **do not manual-unpause**.

### 2. When 12h window PASS + stable ~4h

Merge V3 → V2 on dev, then VM deploy:

```bash
# Dev machine
git checkout V2 && git merge V3
bash scripts/v3_pre_deploy_check.sh
git push origin V2

# VM
NANOUP_AUTOSTASH=1 nanodeploy
git log -1 --oneline   # expect post-merge commit
```

### 3. After V3 deploy (expect)

- Tiered **cooldown** after rebuild/fill (less ping-pong on resume)
- **High-stable WMATIC rotation** when unpaused at ~$31 / 75% FE
- Drawdown throttle / dynamic trim / adverse guard — **default off or `.env` tuned**; review `.env` after `nanoup` merge

---

## Commit ladder (reference)

| Tag / phase | Commit | Purpose |
|-------------|--------|---------|
| abc | `61adb81b` | Tiered FE runway |
| abc+ops | `9d171080` | Flow PnL, opex, adverse-day |
| abc+auto | `e06cd360` | FE fallback refresh, seed EMA |
| headroom | `ed1dc1cb` | Tiered reserve headroom |
| **derisk** | **`02c5fcd7`** | **VM live — high-FE de-risk trim** |
| v3 wave1 | `e0593a32` | Cooldown, hysteresis, flow sync, nano_green |
| **v3 full** | **`de1c1c24`** | **+ dynamic trim, throttle, churn, high-stable rotation** |

---

## Known open items (not blocking break)

| Item | Severity | Notes |
|------|----------|-------|
| `swap_executor.py` ~3750 lines | Tech debt | Split in future refactor sprint; new logic in `nanoclaw/*` |
| `.env.example` ~540 lines | Ops debt | Move catalog to `docs/ENV_REFERENCE.md` later |
| Turnover parser | Fixed in `02c5fcd7` | Ignores wei-scale mis-attribution |
| VM `scripts/*.sh` local edits | Ops | Stashed as `vm-local-scripts`; review `git stash list` |
| Realistic +10%/day target | Expectation | Needs market luck; engineering target **+$4–8 / 1–2 weeks** post-unpause |

---

## Key env knobs (stage)

```bash
STAGE_SEED_USD=158
OPERATING_RESERVE_TIERED_EXEMPT_ENABLED=false
FE_STABLE_RUNWAY_TIERED_RESERVE_HEADROOM_USD=2
FE_STABLE_RUNWAY_TIERED_MIN_NOTIONAL_USD=5
FE_STABLE_RUNWAY_DERISK_ENABLED=true
EXTERNAL_AUTO_PAUSE_ENABLED=true
EXTERNAL_AUTO_WINDOW_MIN_PCT=-2.0
# V3-only until merge:
FE_STABLE_RUNWAY_TIERED_COOLDOWN_HOURS=4
MAIN_STRATEGY_HIGH_STABLE_WMATIC_ROTATION_ENABLED=true
DRAWDOWN_THROTTLE_ENABLED=true   # review before merge — defaults aggressive in .env.example
```

---

## Docs index

- [`OPERATOR_PNL_MARK_VS_TRADE.md`](OPERATOR_PNL_MARK_VS_TRADE.md) — mark vs trade, derisk, headroom, churn
- [`AGENT_SPRINT_PROMPTS_V3.md`](AGENT_SPRINT_PROMPTS_V3.md) — parallel agent prompts (waves 1–3 done)
- [`DEV_WORKFLOW.md`](DEV_WORKFLOW.md) — V3 merge gate §
- [`AGENT_SPRINT_PROMPTS.md`](AGENT_SPRINT_PROMPTS.md) — V2 sprint history

---

*Generated at thread handoff — Jun 1 2026. Resume from `nano12h` + this file.*
