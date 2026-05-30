# Master Brainstorm — Operator ↔ AI working memory

> **Purpose.** This file is the working memory of the **master chat session**: the long-running operator/AI brainstorming loop. It is **not** project documentation (that's `AI_CONTEXT.md`) and **not** roadmap (that's `ROADMAP.md`). It tracks open threads, decisions, and handoffs to **side chats** that do the actual coding.
>
> **Style:** append-only for decisions, append log, and current focus. **Completed side-chat handoff prompts are removed** once merged (history stays in Append log + git). Only the **active** handoff stays verbatim.
>
> **Two-chat model:**
>
> - **Master chat** (this one) — strategy, triage, evidence collection, handoff-prompt drafting, side-chat review/merge gate. No code edits.
> - **Side chats** — implement one cleanup / one feature / one fix. Open with a handoff prompt from this file. Push to `origin/V2`. Close.
>
> When master gets too long, fork it with the **"Master chat continuation" prompt** at the bottom of this file. The new master reads this doc as its sole context.

---

## Current focus (top of stack)

- **CODE FREEZE (2026-05-30 → ~7 Jun IST leave):** **`bf849af7`** deployed on VM. **No side chats** until operator returns. Handoff: **`docs/OPERATOR_CODE_FREEZE_2026-05-30.md`** (commands, health, multi-venue roadmap, new-thread prompt).
- **VM state @ freeze:** TOTAL **~$130.89** · stables **$17.91** · session **−1.04%** · **3 fills** UTC day · `Risk=LOW` · dust defer **$9.33 < $10** blocking new BUYs · **`HONOR_FULL_BLOCKLIST=false`** (nanoup wiped `true` — footgun). **`pgrep clean_swap`** was empty in snapshot — verify before long leave.
- **Merged @ freeze:** Cleanup **#6** FE runway · **P1** spot cache · nanodaily skips · blocklist honor · **nano_watch**.
- **Operator mandate (2026-05-30):** Multi-venue **leverage-first** (not Polygon-only long term); **~25% energy** through **30 Jun**; **binary go/no-go** trading vs SaaS/content; months on stage — **expectancy still unproven**.
- **Post-freeze P0 side chats:** preserve `X_SIGNAL_HONOR_FULL_BLOCKLIST` on nanoup · default `NANOUP_AUTOSTASH=1` · **FE-heavy BUY guard** (stables < $40 + fe_share > 55%) · alias **`ns`** snapshot.
- **2026-05-29 stop-bleed + rotation —** `ROADMAP.md` § [Session log 2026-05-29](ROADMAP.md#session-log-2026-05-29-stage-instance-a--stop-bleed--rotation--llm). VM **`15723c3f`**+; session **11 fills** · session PnL **~-0.63%** (PnL gate failing).
- **Parked (LLM):** Grok advisory (Phase B) → gate (Phase C); PhotonBull ≠ Polygon execution.
- **Turnover metrics — MERGED `22f96757`:** `turnover_multiple_*` in ROTATION / `nanovel`.
- **Cleanup #5 — LIVE `d1b82635`:** defensive_pause uses combined stables.
- **Parked (v3):** top-up must not count as profit in `portfolio_history` / session %.
- **`nanodaily` exit=127:** bare `python` not on PATH — **`source .venv/bin/activate`** before `nanodaily`, or use **`nh`** / **`nanopnl`** (worked in operator session).
- **Parked:** Instance B; 9 legacy test failures; in-flight stables race.
- **Operator north star:** +ve net PnL on stage → seed scale → rotation velocity → ~$100k (release train).

**Merged cleanups (see [Append log](#append-log-side-chat-reports-come-here)):** #1–#4 as before · **#5 `d1b82635`** defensive_pause / cycle risk stables.

## Instance B (parked — later)

New **wallet** + **VM**; never two writers on one key (`AI_CONTEXT.md`). No handoff drafted yet — master will add when operator starts B.

## Velocity roadmap (+ve PnL → seed rotation throughput)

> **Velocity** = `velocity_fills_per_day` (float): **on-chain swap count** for the UTC day — count lines matching **`Swap executed successfully!`** in `real_cron.log`, attributed to the cycle via the preceding `=== CYCLE <unix_ts>` (log lines have **no** `YYYY-MM-DD` prefix; **do not** `grep "$(date -u +%Y-%m-%d)"` — that always returns 0 for swaps). **Not** `TRADE_ATTRIBUTION | Asset=…` (plan/intent only). **Not** dollar volume.  
> **Turnover** = `notional_turnover_multiple_per_day` (float): USD swapped ÷ seed TOTAL (e.g. ~$250 on ~$120 seed ≈ **2.0 turnover**, not **2.0 velocity**).  
> **PnL gates:** **Session** = per **tag/deploy** (`nanopnl --reset-session` at t=0 → current `TOTAL` is session anchor; **do not** reset session → session PnL continues). **Portfolio baseline** (`portfolio_baseline.json`) = long-lived wallet epoch — **set once** on fresh start, **ideally never changed**; 24h / multi-day windows can cross sessions while baseline stays fixed. **Do not** use CSV first-row **+47%**. **Top-ups** = v3 (must not count as profit); until then fix top-up logic, not constant re-baselining.


| Phase                   | Window              | `velocity_fills_per_day` (float) | `session_pnl_pct` (float) | `notional_turnover_multiple_per_day` (float) | How you know                                                           |
| ----------------------- | ------------------- | -------------------------------- | ------------------------- | -------------------------------------------- | ---------------------------------------------------------------------- |
| **0 — Truth + unblock** | days 0–2            | (no target)                      | baseline @ reset          | —                                            | MetaMask ≈ bot ≤$1; `Risk=LOW`; cleanup3/4/5 on VM ✓                      |
| **1 — Fill rate**       | days 2–9 (P0 clock) | **≥ 0.5** → **≥ 1.0**            | **> 0.0** sustained on **session** (post-tag reset) | **≥ 0.25** (e.g. ~$30 on $120)               | `Swap executed` count (UTC via CYCLE ts); `nanopnl` **Session PnL** |
| **2 — Velocity v1**     | post-P0             | **≥ 2.0** (stretch **5.0**)      | **≥ 1.0** weekly avg      | **≥ 0.5** (~$60/day on $120)                 | LINK-only + cooldown caps; Instance B may probe higher                 |
| **3 — Throughput v2**   | edge proven         | **≥ 2.0** stable                 | **≥ 1.0** / week          | **≥ 3.0** (full seed 3×/day)                 | Only after positive edge per fill; lift `max_copy_trade_pct` with logs |
| **4 — Scale capital**   | v3.0                | scale with seed                  | P0 **> 2.0** net / 7d     | —                                            | $1k→$25k→$100k after P0 + DD **< 10.0**                                |


**P0 bar (floats):** 7.0 days live · **≥ 40.0** swaps · **net_pnl_pct > 2.0** · **max_drawdown_pct < 10.0** · post-#3/#4 accounting.

**Throughput levers (after #5 — mostly env/ops on Instance B):**

1. Post-#5: if still no fills — `LOW EDGE`, `insufficient_per_variant_usdc`, STF pause, cooldown.
2. `**control.json`** `max_copy_trade_pct=0.02` — caps sizing; lift only with fill+PnL evidence.
3. **Blocklist** — only LINK trades today; unblocking WETH/LINK rotation needs deliberate `.xsignal_blocked_symbols` edits.
4. `**X_SIGNAL_EQUITY_COOLDOWN_SECONDS`** / per-asset 30m post-fill — dominant cap on fills/day per symbol.
5. `**COOLDOWN_MINUTES=1**` — already aggressive (~1440 cycles/day max).

## PnL accounting (two layers — keep simple)

| Layer | File / command | When it changes | Use for |
|-------|----------------|-----------------|---------|
| **Portfolio baseline** | `portfolio_baseline.json` (+ `PORTFOLIO_BASELINE_USD=0`) | **Once** per wallet epoch (fresh start); **not** each tag | Long-horizon “since baseline”; spans 24h/5d across sessions |
| **Session** | `nanopnl --reset-session` → `portfolio_session_baseline.json` | Each **tag/deploy** you treat as a new train (t=0 = current `TOTAL`) | **Primary release-train gate** (e.g. P0 phase 1) |
| **24h** | `portfolio_history.csv` | Automatic | Rolling day; useful after baseline file is valid |

**Operator rules:** KISS as default; trading/LLM will need depth — simplify over time (refactors, cleanups). **VM:** readonly diagnostics in master chat; **operator files** (`portfolio_baseline.json`, `.env`) on VM are OK; **code changes** → side chat handoff, not ad-hoc VM edits.

**Why “Since baseline” still +47%:** `portfolio_baseline.json` was likely **invalid** (import side-effects wrote garbage into `baseline_usd`). Resolver fell back to **CSV first row** (~$81.81). **Session PnL 0%** proves `--reset-session` worked.

**A) Once per wallet epoch** — fix portfolio baseline (quiet TOTAL, no `python3 -c` import):

```bash
cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate
grep '^PORTFOLIO_BASELINE_USD=' .env   # must be 0

TOTAL=$(nanopnl 2>/dev/null | awk '/^   TOTAL:/ {gsub(/\$/,"",$2); print $2; exit}')
WALLET=$(grep -E '^WALLET=' .env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
COMMIT=$(git rev-parse --short HEAD)
TAG=$(git tag -l 'v2.8.0-cleanup5' 2>/dev/null | head -1)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

python3 <<PY
import json
from pathlib import Path
payload = {
    "wallet": "${WALLET}",
    "baseline_usd": float("${TOTAL}"),
    "commit": "${COMMIT}",
    "tag": "${TAG}",
    "reset_at": "${NOW}",
    "note": "wallet-epoch baseline (set once); top-ups v3",
}
Path("portfolio_baseline.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print("wrote portfolio_baseline.json baseline_usd=", payload["baseline_usd"])
PY

cat portfolio_baseline.json
nanopnl | grep -E 'TOTAL|Since baseline|Session PnL'
# Expect: Since baseline ≈ $0.00 (0.00%)
```

**B) Each tag deploy** — session only (baseline file untouched):

```bash
git tag v2.8.0-cleanup5   # if not tagged yet
nanopnl --reset-session
nanopnl | grep -E 'Session PnL|Session start|TOTAL'
# Expect: Session PnL 0% at reset; record tag in operator log / MASTER append
```

**C) Next `nanoup`:** `nanoup` → `nanopnl --reset-session` → done (no rewrite of `portfolio_baseline.json` unless new wallet). File is **gitignored** (VM-only); if an older tree blocks `nanoup` on `?? portfolio_baseline.json`, run **`NANOUP_AUTOSTASH=1 nanoup`** once or `git pull` after updating `.gitignore`.

**Daily operator metric (add to habit):**

```bash
source .venv/bin/activate
nanopnl | grep -E 'TOTAL|Session PnL|Since baseline|velocity_fills|turnover_'
nanovel    # rotation only: fills + turnover multiples
nh         # RPC gate
nanodaily  # includes ROTATION block in --daily-summary
grep "X-SIGNAL BUY RISK" real_cron.log | tail -1
grep '=== CYCLE' real_cron.log | tail -1
```

**Velocity:** `velocity_fills_per_day_utc` = calendar UTC day; `velocity_fills_session` = fills since `portfolio_session_baseline.json` (tag/deploy reset). Use **session** for release-train gates; UTC day includes pre-reset fills (why 13 UTC vs fewer session is normal).

## Recent merged work (commits on `origin/V2`)


| Commit     | Title                                                                           | Side chat            | Status                                              |
| ---------- | ------------------------------------------------------------------------------- | -------------------- | --------------------------------------------------- |
| `22f96757` | PnL turnover: `turnover_multiple_*` + `sum_turnover_usd` in ROTATION / nanovel  | turnover side chat   | merged 2026-05-27; VM pull pending                  |
| `580217bf` | Velocity in pnl_report + nanodaily venv python + `portfolio_baseline.json` gitignore | turnover prep        | merged 2026-05-26; on VM                            |
| `76946ea3` | Cleanup #3 (4/4): suppress `BALANCE READ FAILED` spam after first per-token log | Cleanup #3 side chat | merged 2026-05-26                                   |
| `9adb388d` | Cleanup #3 (3/4): pin stables drift invariants at `get_balances()` surface      | Cleanup #3 side chat | merged 2026-05-26                                   |
| `9abb0881` | Cleanup #3 (2/4): treat `current_price_usd` as a true FALLBACK FLOOR for FE_USD | Cleanup #3 side chat | merged 2026-05-26                                   |
| `d1b82635` | Cleanup #5: cycle risk / defensive_pause uses combined stables (DRY buffer helper) | Cleanup #5 side chat | merged 2026-05-26; **VM deploy pending** (`nanoup`) |
| `844b2e21` | Cleanup #4: X-SIGNAL BUY defense uses combined stables (rotation unblock)       | Cleanup #4 side chat | merged + deployed 2026-05-26; tag `v2.8.0-cleanup4` |
| `9f85cbcb` | Cleanup #3 (1/4): surface POL_USD in WALLET TOTAL USD for operator parity       | Cleanup #3 side chat | merged 2026-05-26                                   |
| `30fb17b9` | Cleanup #2: harden `_force_max_approval` against startup-crash landmine         | (other thread)       | merged + deployed to VM 2026-05-26                  |
| `fb5eac6e` | Cleanup #1: route WALLET TOTAL USD through one helper                           | (other thread)       | merged + deployed to VM 2026-05-26                  |
| `bbfa05d9` | Enhance FE_USD fallback + diagnostics for unquoted assets                       | this master          | merged + deployed                                   |
| `ca6ca24c` | Lower WBTC min notional + tighten slippage                                      | this master          | merged + deployed                                   |
| `ea910953` | POL `_pol_target_for_trade` + `POL_EXECUTION_GAS_*` pre-trade top-up            | stop-bleed side chat | merged 2026-05-29; VM deployed                      |
| `15723c3f` | Fix `_pol_target_for_trade` via `runtime` + `clean_swap` re-export              | stop-bleed side chat | merged 2026-05-29; VM deployed                      |
| `069c9976` | Loss-cut dust min + blocklist when only LINK followed                           | Option C             | merged (prior in session)                           |
| `17f3f421` | 300s cycle lock + loss-cut pre-mark cooldown                                    | Option C             | merged (prior in session)                           |
| `261e56f9` | Persist `asset_last_trade_unix` in `bot_state.json`                             | Option C             | merged (prior in session)                           |


## Open questions / parked threads

- **Seed-capital scaling** (~$120 → $1k → $25k → $100k). Parked until P0 window + stable post-#5 fills; books improved (#3–#5). Verify wallet-vs-bot ≤$1 in steady state before scaling.
- **Pre-existing 9 test failures** (profit-take mocks, RPC bleed). Parked for a future cleanup (not #5).
- **In-flight swap reservation race** (stables snapshot vs swap settle). Parked; steady-state invariants pinned in #3 tests.
- **`current_price_usd` auto fallback (BACKLOG P1 — `ROADMAP.md` § Backlog):** persist last good quoter spot per symbol; until shipped, manual floor in `followed_equities.json` (WETH **2000** on Instance A, 2026-05-29). Stale fallback **above** spot still overstates TOTAL.
- **Cleanup #6 — FE stable runway (2026-05-30):** low-stables rebuild is **WMATIC-only**; post-rotation **WMATIC=0 + FE~89%** deadlocks reserve path. Side chat drafted below Current focus.
- **Multi-venue expansion (operator aspiration):** commodities / stocks / crypto / futures / options — **parked** until Polygon session PnL > 0 + 12h–24h stable monitoring; intelligence layer can ingest cross-asset signals, execution stays Polygon until adapters ship.
- **Instance A blocklist (2026-05-29):** `LINK_ALPHA`, `WMATIC_ALPHA`, `WBTC_ALPHA` blocked; **only `WETH_ALPHA`** open for USDC→equity rotation. See `ROADMAP.md` session log.
- **Quote-fail fallback:** try next X-SIGNAL plan candidate when primary symbol has no quotable path (WBTC proved this). Side chat TBD.
- **Overlapping `clean_swap` processes** when quote ramp > cron interval — operator uses `nanokill` + single `nanoup`; code hardening TBD.

## Decisions log


| Date       | Decision                                                                                   | Rationale                                                                                                                                                         |
| ---------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-26 | Adopt master/side-chat split; this file is the seam                                        | Master threads were exceeding usable context; side chats need surgical scope                                                                                      |
| 2026-05-26 | `WBTC_ALPHA` in blocklist; balance-read noise gate deferred to Cleanup #3                  | Trading impact zero; log impact medium                                                                                                                            |
| 2026-05-26 | `compute_authoritative_total_usd` is the **only** sanctioned source of `WALLET TOTAL USD`  | Cleanup #1 (`fb5eac6e`). Side chats must not re-introduce regex parsing.                                                                                          |
| 2026-05-26 | `_force_max_approval` wrapper no longer passes `force=True`                                | Cleanup #2 (`30fb17b9`). Closes May 24 crash-loop landmine.                                                                                                       |
| 2026-05-26 | `current_price_usd` in `followed_equities.json` is a **fallback floor**, not authoritative | Cleanup #3 (`9abb0881`): effective FE_USD = `max(live_quote_usdt, bal × fallback)`; live wins when ≥ fallback; `FE_USD FALLBACK FLOOR APPLIED` when fallback wins |
| 2026-05-26 | `Balances.pol_usd` + `POL_USD=` on `WALLET TOTAL USD` line                                 | Cleanup #3 (`9f85cbcb`): POL was already in TOTAL; visibility only for MetaMask reconcile                                                                         |
| 2026-05-26 | `BALANCE READ FAILED` log-once per `(token, wallet)` in `get_token_balance`                | Cleanup #3 (`76946ea3`); blocklist does not gate inventory reads                                                                                                  |
| 2026-05-26 | X-SIGNAL BUY buffer checks use **USDT+USDC** (`onchain_stable_usd`), not USDT alone        | Cleanup #4 (`844b2e21`); USDT divergence stays USDT-only                                                                                                          |
| 2026-05-26 | Cycle risk / `_defensive_pause_state` uses **STABLE_USD** via `_x_signal_buy_risk_level_from_buffers` | Cleanup #5 (`d1b82635`); `_cycle_risk_level` passes `balances.usdc`                                                                                              |
| 2026-05-26 | **PnL:** portfolio baseline **once per wallet epoch**; **session** reset per **tag/deploy** only | No guessed $300 seed; top-ups ≠ profit (v3); VM operator files OK, code → side chat                                                                                  |
| 2026-05-29 | **Stop bleed:** `ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false` on stage; loss-cut not relied on for LINK dust | Gas spiral from 0.19 POL vs ~0.22 tx; blocklist stops WBTC quote waste |
| 2026-05-29 | **POL pre-trade target** = `max(MIN_POL floor, POL_EXECUTION_GAS_UNITS × gwei × mult)` | `ea910953`; fixes false “POL sufficient” at 0.19 POL |
| 2026-05-29 | **`nanoup` preserves** operator loss-cut / recovery flags | `ENV_APPLY_PRESERVE_KEYS` in `env_sync.py` |
| 2026-05-29 | **PhotonBull / X sentiment** → external intelligence only; **no** US ticker → Polygon swap | LLM phases B–E in `ROADMAP.md` session log §6 |
| 2026-05-29 | **Rotation leg:** WETH only until `EXEC SUCCESS`; WBTC blocked (no Polygon liquidity) | WMATIC blocked (already hold 70 qty) |
| 2026-05-30 | **ASAP PnL > 0**; **12h max** unattended monitoring; short-term rotation over long hold | Operator directive; multi-venue aspiration recorded, Polygon execution first |
| 2026-05-30 | **P0 deadlock:** WMATIC=0 + FE overweight → STABLE RESERVE no-op; need **FE→USDC trim** (#6) | P0 triage logs + MetaMask reconcile ($131.76 ≈ bot) |


---

## Master chat continuation prompt

> Use this when **this master thread** gets too long. Open a fresh chat and paste this block. The new master picks up where this one left off, with `MASTER_BRAINSTORM.md` as its working memory.

```
ROLE: You are the master chat for the nanoclaw bot — operator's brainstorming partner, triage, and side-chat dispatcher. You do NOT write production code in this thread; you draft handoff prompts and review side-chat output.

CONTEXT FILES (read these first, in order):
1. MASTER_BRAINSTORM.md — your working memory; current focus, open threads, decisions log, append log. THIS IS YOUR PRIMARY CONTEXT.
2. AI_CONTEXT.md — project governance, design rules, "Today's learnings" (chronological incident log).
3. ROADMAP.md — directional milestones.
4. .cursor/rules/*.mdc — task-completion-discipline + karpathy-guidelines. Hold side chats to these.

OPERATING MODEL:
- This thread is master. Code edits happen in side chats opened from this thread.
- For each cleanup / feature / fix, draft a handoff prompt before dispatching; remove it from MASTER_BRAINSTORM.md once merged (append log keeps the summary).
- When a side chat finishes, update MASTER_BRAINSTORM.md (Recent merged work + Decisions log + Append log + Current focus).
- Surface evidence with citations (commit hashes, log snippets, file:line). Do not narrate.
- When the operator asks a strategy question (e.g. "should I scale capital?"), answer in master; do not spawn a side chat.

CURRENT STATE (read MASTER_BRAINSTORM.md "Current focus" + "Open questions" for the live picture).

WORKSPACE RULES (always-applied, non-negotiable):
- Karpathy: minimum diff, no speculative work, surgical changes, ask before assuming.
- task-completion-discipline: tests + docs + .env.example updates with every behavior change.

START BY: reading MASTER_BRAINSTORM.md in full, then ask the operator what's next.
```

---

## Active side-chat handoff (remove when merged)

### Cleanup #6 — FE stable runway (P0 — open Instance A deadlock)

```
ROLE: Side chat on origin/V2. Surgical fix only.

PROBLEM (Instance A @ 15723c3f, 2026-05-30):
- Wallet: ~$131 TOTAL, stables ~$13.27, WETH FE_USD ~$117 (89%), WMATIC=0.
- MAIN_STRATEGY STABLE RESERVE plans WMATIC→USDC but amount_in=0 → quiet/no actionable.
- X-SIGNAL keeps USDC→WETH BUY (signal 0.87, reduced HIGH-risk bypass) — wrong direction when FE overweight + stables below high_trigger ($15).
- MetaMask reconciles bot TOTAL within ~$0.33.

ACCEPTANCE:
1) When combined stables < MAIN_STRATEGY_LOW_STABLES_DUST_REBUILD_MAX_STABLE_USD (default $15) AND portfolio > $130 AND followed_equity_usd / total_portfolio_usd >= env threshold (default 0.55): prefer partial EQUITY→USDC trim on highest FE holding (start WETH_ALPHA) targeting stables toward X_SIGNAL high buffer (~$40), BEFORE any USDC→EQUITY BUY in same cycle.
2) Block or defer USDC→EQUITY X-SIGNAL BUY when (1) applies (reuse/extend _apply_low_stables_rebuild_rotation_precedence — not just precedence reorder, hard block BUY).
3) Log: `[nanoclaw] FE STABLE RUNWAY TRIM | sym=… | sell_fraction=… | stable_usd=… | fe_share=…`
4) Tests: Instance A balance fixture (stables $13, WMATIC 0, FE $117) → trim plan not WETH BUY; ample stables → unchanged; WMATIC rebuild path unchanged when wmatic>0.
5) `.env.example` keys + AI_CONTEXT.md learnings entry. pytest green on touched modules.

OUT OF SCOPE: blocklist edits, manual operator swaps, multi-venue.
```

---

## Append log (side-chat reports come here)

### 2026-05-30 — Code freeze checkpoint (Instance A @ bf849af7)

- **Deploy:** `bf849af7` on VM; P1 `FE_USD AUTO_FLOOR_UPDATE` live; Cleanup #6 shipped (runway not seen yet — stables $17.91 > $15).
- **Session:** −1.04%; 3× WETH BUY drained stables $50→$18 post-deploy; dust defer now blocks $9.33 BUYs.
- **Blocklist:** all 4 symbols listed; `HONOR_FULL_BLOCKLIST=false` after nanoup → ignore-all-blocks warning once; execution blocks WMATIC individually.
- **Leave:** `control.json` **paused=true** + **operator_pause_lock=true**; `PLAN SELECTED` may still log (plan-only); verify `[CONTROL] paused=True` + no post-pause `EXEC SUCCESS`.
- **Docs:** `docs/OPERATOR_CODE_FREEZE_2026-05-30.md` @ `78ea6948`; **`docs/GROK_HEAVY_STRATEGY_REVIEW_2026-05-30.md`** (full Grok Heavy output + Cursor synthesis).
- **TODO (operator):** copy-trading audit tonight — `followed_wallets.json` likely token addresses not X/trader wallets.
- **Grok verdict:** fix plumbing (FE guard, blocklist preserve, wallet list) before expecting 48h green; Polygon-only until proof; content pivot over SaaS if 30 Jun fail.

### 2026-05-30 — P0 triage: FE overweight / stables deadlock (Instance A)

- **Evidence:** P0 grep; MetaMask Polygon tab **$131.76** (WETH $117.10, USDC $13.27, POL $1.39); bot **$131.43**; `control.json` paused=false, stable_usd=13.27, wmatic=0.
- **Dominant lifetime skips:** protection no-action (340), defensive_pause copy (158), dust deferred (WMATIC era).
- **Live cycle:** `Risk=HIGH` (stable_usd $13.27 < $15) · `PLAN SELECTED WETH_ALPHA BUY` · `STABLE RESERVE` quiet · session PnL **-0.63%**.
- **Root cause:** Low-stables rebuild + reserve paths are **WMATIC-centric**; post-WETH rotation book has **no WMATIC** to sell into stables.
- **Ops unblock:** manual WETH→USDC ~$25–40 OR temp block WETH BUY + `ALLOW_REDUCED_HIGH_RISK_XSIGNAL=false`.
- **Code:** Cleanup **#6** handoff above.

### 2026-05-29 — Stop bleed, POL execution target, rotation unblock (Instance A)

- **Commits:** `261e56f9`, `17f3f421`, `069c9976`, `ea910953`, `15723c3f` (+ earlier loss-cut `7b231434` / `a3f3c9f8` in same arc).
- **Operator VM:** `0x05eF…` · ~$124 USDC · LINK 0 on-chain · POL ~16 · session ~+0.18% · velocity 0 until WETH fill.
- **Incidents closed:** loss-cut gas spiral; `nanoup` resetting `ALLOW_HIGH_RISK`; `AttributeError` `_pol_target_for_trade`; WBTC unquotable path.
- **Safe config:** `ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false`; `.xsignal_blocked_symbols` = LINK, WMATIC, WBTC; cron `*/2` + `COOLDOWN_MINUTES=1`.
- **Brainstorm captured:** PhotonBull ≠ Polygon; LLM hybrid layers (advisory → gate → control.json → multi-venue) in **`ROADMAP.md` session log**.
- **Tests:** `test_runtime_pol_topup`, `test_env_sync` preserve keys, `test_high_risk_loss_cut`, startup gas bootstrap (local).
- **Next:** single-process WETH `EXEC SUCCESS`; then Phase 1 velocity ≥ 0.5/day UTC.

### 2026-05-26 — Cleanup #3 — PnL accounting drift (POL visibility + LINK fallback floor + stables invariants + WBTC noise gate)

- Commits (origin/V2):
  - `9f85cbcb` Cleanup #3 (1/4): surface POL_USD in WALLET TOTAL USD for operator parity
  - `9abb0881` Cleanup #3 (2/4): treat `current_price_usd` as a true FALLBACK FLOOR for FE_USD
  - `9adb388d` Cleanup #3 (3/4): pin stables drift invariants at `get_balances()` surface
  - `76946ea3` Cleanup #3 (4/4): suppress `BALANCE READ FAILED` spam after first per-token log
- Tests: canonical 4-file gate 47 → 52 passing (+5). Extended runtime gate (adds `test_runtime_usdc_native.py` + `test_runtime_get_token_balance.py`) 47 → 61 (+14). Pre-existing 9 failures unchanged (verified by running the failing set against the pre-#3 tree); still deferred to Cleanup #4.
- Notes:
  - **POL was already in TOTAL arithmetically** — Cleanup #3 part 1 added operator visibility (`Balances.pol_usd` field + `POL_USD=$X.XX` in the log line). No formula change.
  - **LINK MTM**: `current_price_usd` is now a true fallback FLOOR (`max(live, bal × fallback)`). New diagnostic `FE_USD FALLBACK FLOOR APPLIED` fires when fallback wins. Operators MUST refresh fallbacks periodically — added as a parked thread.
  - **Stables drift**: no behavior change. Source is correct; most likely cause of the 2026-05-26 ±$8.56 was an in-flight swap reservation race (added as a parked thread for Cleanup #4). Regression tests now pin steady-state invariants.
  - **WBTC noise gate**: per-(token, wallet) latch in `get_token_balance` logs once, then suppresses. Per-token AND per-wallet so fresh wallets still get diagnostics.
  - **.env impact**: none. No new knobs.
  - **AI_CONTEXT.md**: "Today's learnings (26 May 2026 — Cleanup #3)" entry added at top of the learnings section.
  - **Operator next step**: re-deploy V2 to VM; verify wallet-vs-bot match within $1 in steady state on a few clean cycles before re-opening scaling math.

### 2026-05-26 — Cleanup #4 — X-SIGNAL BUY defense uses combined stables

- Commits: `844b2e21` fix(signal): X-SIGNAL BUY defense uses combined stables for rotation
- Tests: canonical gate 52 → 57 (+5 in `test_signal_x_signal_buy_risk.py`); 57/57 green
- Notes: VM pre-deploy still showed `usdt_below_high_buffer` at `9cc9100c`. After `nanoup` to `844b2e21`, grep for `STABLE_USD=$40` + LINK 0.81 → expect **no** `buy_plans_paused=True` with sole reason `usdt_below_high_buffer`. Next blockers may be `no_plan`, `LOW EDGE`, per-variant USDC — triage separately.

### 2026-05-26 — Cleanup #5 — defensive_pause / cycle risk uses combined stables

- Commits: `d1b826357a48ec2f3622eb5456fedef7926a10ce` — shared `_x_signal_buy_risk_level_from_buffers`; `_cycle_risk_level` passes `usdc`; `test_defensive_pause` uses usdt=9, usdc=2 for HIGH
- Tests: canonical gate **57 → 59** (+2 in `test_signal_x_signal_buy_risk.py`); **59/59** green
- Notes: Split-brain after #4 — `Risk=LOW` + `PLAN SELECTED` but `defensive_pause (risk=HIGH) — pausing X-signal BUY` on VM @ `844b2e21`. Operator VM @ 17:40 UTC still **`844b2e21`** → **`nanoup` required**. `.env.example` unchanged. **Velocity today (UTC):** ~**10** fills via `Swap executed successfully!` + CYCLE ts (not date-grep). **Session PnL:** ~**-0.15%** since 09:54 reset.

### 2026-05-27 — PnL turnover metrics (rotation reporting)

- Commits: `22f96757` — `sum_turnover_usd`, `format_turnover_lines`, ROTATION block + `--velocity-only` / `nanovel`
- Tests: `test_pnl_report.py` **30/30** (+5 turnover tests)
- Notes: **turnover_multiple** = notional ÷ current seed TOTAL; ignores plan-only `TRADE_ATTRIBUTION | Asset=`. Operator top-up ~$16 USDT in flight — **no session/baseline reset** after transfer.

