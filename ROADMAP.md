
# v3.0 Roadmap: Hybrid Agent System + Positive PnL

**Goal**: Move from slow iterative patching to a **Hybrid Architecture** while achieving consistent positive Session PnL as fast as possible.

**Target Timeline**: 4–5 weeks for a production-ready version with positive expectancy.

**Core Principles**
- Speed through **heavy reuse** of existing open-source work
- GitHub + single `ROADMAP.md` as the source of truth
- Keep `nanoclaw` as the Execution Layer (for now)
- Build intelligence in an **External Agent + Risk Layer**
- Run multiple plays in parallel under one controlled system
- Stay agile and ready to pivot

---

## Current Status (as of 29 May 2026 — Instance A stage VM)

- **Wallet:** `0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6` · **Branch:** `V2` · **Head (post-fix):** `15723c3f`+ (POL execution target + `_pol_target_for_trade` façade fix)
- **Session PnL:** ~**+0.18%** after `nanopnl --reset-session` (2026-05-29T11:11:38Z) — no longer in free-fall from LINK loss-cut / gas bleed
- **Rotation:** `velocity_fills_session=0` until first **`EXEC SUCCESS`** on an unblocked asset (WETH path live; WBTC blocked)
- **Capital:** ~**$124 USDC** + ~**70 WMATIC** (qty) · **LINK on-chain:** 0 · **POL:** ~16 native (healthy vs execution target ~0.20)
- **Mode:** Stop-bleed config active (loss-cut off, blocklist, POL fix deployed). **Next:** single-process WETH fill → Phase 1 velocity gate (≥0.5 fills/day UTC)

Full incident + operator playbook + LLM brainstorm: **[Session log 2026-05-29](#session-log-2026-05-29-stage-instance-a--stop-bleed--rotation--llm)** below.

---

## Phases

### Phase 0: Maximum Defensive Mode (Current)
**Status**: In progress

**Tasks**
- Keep bot in defensive mode
- Monitor Session PnL and protection frequency for 24–48 hours
- Decide whether to further reduce exposure or pause new entries

**Cursor Prompt (when needed)**:
> Review current defensive settings and recent protection triggers. Suggest any additional short-term changes to further reduce risk.

---

### Phase 1: Design External Agent + Risk Layer (Next Priority)

**Goal**: Move risk decisions and strategy control **outside** the core trading bot so we can iterate much faster.

**Key Requirements**
- External layer should control/pause `nanoclaw`
- Support multiple strategies (current + Polymarket)
- Easy to experiment with (agentic style)

**Focus**
- Heavily leverage patterns from `HKUDS/AI-Trader` and `second-state/fintool`
- Design clean separation between Execution and Intelligence layers

**Cursor Prompt (when starting this phase)**:
> Propose a modular architecture for the External Risk + Agent Layer. Prioritize speed of iteration and reuse of existing patterns from HKUDS/AI-Trader and second-state/fintool.

---

### Phase 2: Codebase Audit & Cleanup

**Goal**: Reduce technical debt and make the codebase more maintainable and modular.

**Tasks**
- Identify legacy and unused code
- Find brittle coupling points
- Propose cleanup priority and modular improvements
- **Auto FE_USD fallback floor** (see [Backlog P1](#backlog-prioritized--resume-from-here)) — persist last good on-chain spot per followed symbol; reduce manual `current_price_usd` hygiene

**Cursor Prompt**:
> Perform a high-level audit of the current codebase. List the biggest sources of technical debt and recommend a cleanup priority.

---

### Phase 3: Build External Risk + Agent Layer v1

**Goal**: Create the first working version of the external control layer.

**Tasks**
- Implement basic risk assessment outside the bot
- Add ability to pause/resume trading
- Start moving defensive logic out of `signal.py`

---

### Phase 4: Polymarket Side Strategy (Parallel Track)

**Goal**: Add a second strategy using prediction markets for diversification and learning.

**Approach**
- Start small
- Leverage existing Polymarket bot patterns
- Run under the same risk layer

---

## Open Decisions

- Should we eventually replace parts of `nanoclaw` execution, or keep it long-term as the execution engine?
- Preferred agent framework for the External Layer (`OpenClaw`, custom, or adapt from `HKUDS/AI-Trader`)?
- **LLM last gate:** advisory-only first (`NANOCLAW_AGENT_LAYER_ADVISORY`) vs schema-bound APPROVE/DENY before swap (see [session log](#session-log-2026-05-29-stage-instance-a--stop-bleed--rotation--llm)).
- **X / social sentiment:** ingest as structured signals into `followed_equities.json` / `control.json` — not raw tweet → swap (PhotonBull-style US equities are out of scope for Polygon DEX).

---

## Session log: 2026-05-29 (Stage Instance A — stop bleed, rotation, LLM)

> **Purpose:** Preserve operator + engineering decisions from the 2026-05-29 master/side-chat session so they are not lost in chat history. Technical detail also in `AI_CONTEXT.md` (Today's learnings 29 May) and `MASTER_BRAINSTORM.md` (append log).

### 1. Incident summary (what was bleeding money)

| Symptom | Root cause | Impact |
|--------|------------|--------|
| `insufficient funds for gas` on loss-cut / X-SIGNAL swaps | **POL ~0.19** while real tx cost **~0.22**; `AUTO-POL skipped — POL sufficient` used **static floor ~0.17** only | Gas death spiral: failed broadcasts still burned POL |
| Repeated **LINK loss-cut** trims | In-memory cooldown reset each cron one-shot; **15s** cycle lock expired mid approve/swap; dust plans when LINK → 0 | POL + churn; session drawdown mostly MTM + gas |
| `nanoup` re-enabled loss-cut | Template had `ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=true`; preserve list did not include operator flag until fix | Operator `false` overwritten on deploy |
| **`velocity_fills = 0`** (late session) | `AttributeError: clean_swap has no attribute '_pol_target_for_trade'` crashed every cycle; plus overlapping `clean_swap` / WBTC quote ramp | No rotation despite strong WETH signals |
| **WBTC `EXEC FAILED`** | Polygon **USDC→WBTC** (`0x1BFD6703…`) not quotable; `BALANCE READ FAILED` on same token | Wasted RPC/time; no on-chain fill (not POL bleed) |

**Not bleed:** `MAIN_STRATEGY_OUTCOME | quiet_reason=no_trade` with `actionable=True` for `USDC_TO_EQUITY` — misleading label, not a failed trade.

### 2. Fixes shipped on `origin/V2` (deploy via `nanoup`)

| Commit | What |
|--------|------|
| `261e56f9` | Persist `asset_last_trade_unix` in `bot_state.json`; loss-cut cooldown survives cron restarts |
| `17f3f421` | `NANOCLOW_CYCLE_LOCK_SECONDS=300`; `touch_lock()` + pre-mark loss-cut cooldown before swap |
| `069c9976` | Loss-cut dust min (`HIGH_RISK_LOSS_CUT_MIN_EQUITY_USD`); honor `.xsignal_blocked_symbols` when only LINK followed |
| `7b231434` / `a3f3c9f8` | Loss-cut early path, spot sanity, underwater-any-risk |
| **`ea910953`** | **`_pol_target_for_trade()`** = max(operating floor, `POL_EXECUTION_GAS_UNITS` × gwei × `POL_EXECUTION_GAS_MULTIPLIER`); pre-trade + cycle_start AUTO-POL |
| **`15723c3f`** | `signal.py` uses `runtime._pol_target_for_trade` (fixes façade import); re-export on `clean_swap.py` |

**Env / nanoup (`nanoclaw/env_sync.py`):** preserve **`ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL`**, `ALLOW_REDUCED_HIGH_RISK_XSIGNAL`, `MAIN_STRATEGY_PNL_RECOVERY_MODE`, `PNL_RECOVERY_MODE` across template merge.

**New `.env.example` knobs:** `POL_EXECUTION_GAS_UNITS=600000`, `POL_EXECUTION_GAS_MULTIPLIER=1.15`.

**Execution guards (`swap_executor.py`):** block loss-cut at execution when `ALLOW=false` or dust notional; pre-trade uses `_pol_target_for_trade` not static `MIN_POL_FOR_GAS` alone.

### 3. VM operator playbook (safe config — 29 May 2026)

```bash
# Loss-cut off (nanoup preserves this once set in .env)
ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false

# Block illiquid / unwanted legs; WETH only open for rotation
# File: .xsignal_blocked_symbols (one symbol per line)
LINK_ALPHA
WMATIC_ALPHA
WBTC_ALPHA

# POL / top-up
AUTO_TOPUP_POL=true
MIN_POL_FOR_GAS=0.15
POL_EXECUTION_GAS_UNITS=600000
POL_EXECUTION_GAS_MULTIPLIER=1.15

# Scheduler (one-shot clean_swap per invocation; cron restarts if dead)
# @reboot + */2 * * * * pgrep -f clean_swap.py || nohup .venv/bin/python clean_swap.py >> real_cron.log &
COOLDOWN_MINUTES=1
NANOCLOW_CYCLE_LOCK_SECONDS=300
```

**After `nanoup`:** verify `grep '^ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=' .env` → `false`. **Do not** rely on `sed` before `nanoup` unless value is already in `.env` (preserve reads existing file).

**Single clean cycle (avoid overlapping processes):**

```bash
nanokill && sleep 3 && pgrep -af clean_swap || echo "OK: no bot"
rm -f /tmp/nanoclaw.lock
NANOUP_AUTOSTASH=1 nanoup
sleep 90
grep "2026-05-29" real_cron.log | grep -E 'PLAN SELECTED|EXEC ATTEMPT|EXEC SUCCESS|Skipping blocked|WETH|WBTC|AttributeError' | tail -20
```

**Healthy rotation log:** `Skipping blocked symbol: WBTC_ALPHA` → `X-SIGNAL PLAN SELECTED | WETH_ALPHA` → `EXEC SUCCESS | sym=WETH_ALPHA`.

**Diagnostics (bleed signatures):**

```bash
grep -E 'loss-cut allowed|loss-cut executed|insufficient funds for gas|AUTO-POL failed — trade blocked' real_cron.log | tail -30
python3 -c "from modules import runtime as r; print('pol', r.get_pol_balance(), 'target', r._pol_target_for_trade(None))"
```

### 4. Rotation gates (unchanged north star — `MASTER_BRAINSTORM.md`)

1. **Phase 0:** stop daily bleed → loss-cut off, blocklist, POL target, no crash.
2. **Phase 1:** `velocity_fills_per_day_utc ≥ 0.5` + session PnL **> 0** sustained.
3. **Phase 2+:** scale size / unblock assets only with fill + edge evidence.

**Instance A May 2026:** use **$124 USDC** for **WETH_ALPHA** only until `EXEC SUCCESS`; do not re-open LINK until deliberate strategy change.

### 5. WBTC vs WETH (Polygon execution reality)

- **WBTC_ALPHA** (`0x1BFD67037B42Cf73acf204706795bF64736C834e`): quoter reverts on all fee tiers; keep in **`.xsignal_blocked_symbols`** (also stops balance-read spam per `AI_CONTEXT.md`).
- **WETH_ALPHA** (`0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619`): primary rotation leg on Polygon.
- **WMATIC_ALPHA:** operator holds ~70 WMATIC — block new USDC→WMATIC buys; use WMATIC only via **AUTO-POL unwrap**, not X-SIGNAL churn.

### 6. PhotonBull / X sentiment / LLM (brainstorm — not implemented)

**Reference:** [PhotonBull thread](https://x.com/PhotonBull/status/2060306269987102988) — US equity calls (`$CPSH`, `$ONDS`, `$HLIT`, `$ADTN`), ~811% week, edge described as **predicting X sentiment**. **Not copyable** into nanoclaw (wrong venue, no risk rails, different instruments).

**Hybrid architecture (aligns with Phase 1 ROADMAP above):**

```text
[Intelligence]  Social/X ingest → LLM advisory (Grok) → control.json / signal_strength updates
       ↓ never signs txs directly
[Rules]         signal.py, blocklist, protection, POL target, loss-cut flags
[Execution]     swap_executor → Polygon DEX only
```

| Phase | Work | Env / code |
|-------|------|------------|
| **A (now)** | Deterministic WETH fills, zero bleed | Current VM playbook |
| **B** | Post-cycle **advisory** only | `NANOCLAW_AGENT_LAYER_ADVISORY=true`, `GROK_API_KEY`, keep `NANOCLAW_AGENT_CAN_OVERRIDE_SWAP=false` |
| **C** | Schema **APPROVE/DENY/DEFER** gate before `approve_and_swap` | New side chat; tests required |
| **D** | External agent writes **`control.json`** only | `ROADMAP.md` Phase 3; `modules/agent_layer.py` exists |
| **E** | Multi-venue adapters (Polymarket, CEX) | `ROADMAP.md` Phase 4; shared risk ledger |

**LLM good for:** regime commentary, blocklist suggestions, explaining stuck rotation. **LLM bad for:** `amount_in`, pool routes, minOut, nonce, gas — stay programmatic.

### 7. Open follow-ups (side-chat candidates)

- [ ] **Quote failure fallback:** if WBTC/WETH plan fails all quote ramps, try **next** candidate in `plans[]` same cycle (avoid one bad symbol blocking rotation).
- [ ] **Cron overlap:** long quote ramp + `COOLDOWN_MINUTES=1` + `*/2` cron → overlapping processes; consider `pgrep` + lock file check before start, or serialize in one supervisor.
- [ ] **LLM Phase B:** wire `grok_agent_decision` post-cycle digest to Telegram (no swap override).
- [ ] **X sentiment ingest:** normalized `SignalEvent` → update `followed_equities.json` strengths (no URL-in-prompt trading).
- [ ] Confirm **`MANUAL CORRECT BALANCE`** vs `nanopnl` TOTAL if USDC moved (~$124 vs ~$66 log line) — reconcile on Polygonscan.

---

## Backlog (prioritized — resume from here)

| Priority | Item | Goal | Sketch (for side chat) |
|----------|------|------|----------------------|
| **P1** | **Auto `current_price_usd` fallback floor** | Stop manual `followed_equities.json` edits (e.g. WETH 2500→2000); honest **TOTAL** / session PnL without overstating inventory | **Merged 2026-05-30:** persist `last_good_spot_usd[S]` in `.runtime/fe_usd_spot_cache.json` (gitignored). Effective FE leg stays `max(live_quote, bal × floor)` where `floor_px = min(json_floor, last_good_spot)` (prior cache or first-run live anchor). Upward drift capped via `FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY` (default 5%). Logs: `FE_USD AUTO_FLOOR_UPDATE`, existing `FE_USD FALLBACK FLOOR APPLIED`. Tests in `tests/unit/test_runtime_inventory_mtm.py`. **Does not** change `signal_strength`. |
| P2 | X-SIGNAL next-plan on quote fail | Rotation when one symbol unquotable (WBTC) | See §7 |
| P2 | Cron / lock serialization | No overlapping `clean_swap` during long quote ramp | See §7 |
| P3 | LLM advisory Phase B | Grok digest, no swap override | §6 table |
| P3 | X sentiment → structured signals | Not raw tweet → swap | §6 |

**Operator note (2026-05-29):** ~~Until P1 ships, keep `current_price_usd` in `followed_equities.json` **at or below** spot~~ **P1 merged 2026-05-30** — last-good spot cache in `.runtime/fe_usd_spot_cache.json` auto-caps stale JSON floors; manual JSON hygiene still useful when cache is cold and live=0.

**Resume tomorrow (Instance A):** no config churn; grep `EXEC SUCCESS | WETH`; optional `nanopnl` (do not reset session unless reporting from $132 TOTAL).

### 8. Related docs

- `AI_CONTEXT.md` — loss-cut operator grep/rollback, POL auto top-up, Today's learnings (29 May)
- `MASTER_BRAINSTORM.md` — velocity table, PnL baseline rules, append log 2026-05-29
- `docs/readme-vm-update.md` — `nanoup`, cron, RPC

---

## How to Work

1. Pick one task from this file
2. Copy the relevant section + Cursor prompt
3. Work on it
4. Update this file with progress
5. Commit changes

This file is the single source of truth.

---

## Current Deployment State (as of May 2026)

- Basic **External Risk Layer v1** is implemented and pushed (repo-root **`control.json`**, **`external_layer/control.py`**).
- Layer drives **`paused`** and **`max_copy_trade_pct`** from live **USDT** + **WMATIC** balance tiers (`external_layer/risk_checker.py`).
- **`nanoclaw`** loads **`control.json`** each cycle and **gracefully falls back** to **`.env`** values when the file is missing or unreadable.
- Hybrid setup (**bot + external layer**) is ready for a first deployment on **stage/VM** using **`nanoup`** plus **`./start_external.sh`** (or **`python external_layer/control.py`**) in a separate session/service.
