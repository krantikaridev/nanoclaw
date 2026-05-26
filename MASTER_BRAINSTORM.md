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

- **Cleanup #5 — LIVE on VM `d1b82635` (2026-05-26):** defensive_pause / cycle risk uses **STABLE_USD**. Post-deploy: watch for no new `pausing X-signal BUY` when `stable_usd≥$40`.
- **PnL accounting fix (operator):** `portfolio_baseline.json` write **failed** (noisy `python3 -c` polluted `TOTAL` → invalid JSON → CSV first row ~$82 still drives **+47%**). Re-write baseline with **quiet** command below; then **tag-only session** resets on future deploys.
- **Parked (v3):** top-up / deposit must not count as profit in `portfolio_history` steps.
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
nanopnl | grep -E 'TOTAL|Session PnL|Since baseline|velocity_fills'
nanovel    # rotation only (UTC day + session since --reset-session)
nh         # RPC gate
nanodaily  # includes ROTATION block in --daily-summary
grep "X-SIGNAL BUY RISK" real_cron.log | tail -1
grep '=== CYCLE' real_cron.log | tail -1
```

**Velocity:** `velocity_fills_per_day_utc` = calendar UTC day; `velocity_fills_session` = fills since `portfolio_session_baseline.json` (tag/deploy reset). Use **session** for release-train gates; UTC day includes pre-reset fills (why 13 UTC vs fewer session is normal).

## Recent merged work (commits on `origin/V2`)


| Commit     | Title                                                                           | Side chat            | Status                                              |
| ---------- | ------------------------------------------------------------------------------- | -------------------- | --------------------------------------------------- |
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


## Open questions / parked threads

- **Seed-capital scaling** (~$120 → $1k → $25k → $100k). Parked until P0 window + stable post-#5 fills; books improved (#3–#5). Verify wallet-vs-bot ≤$1 in steady state before scaling.
- **Pre-existing 9 test failures** (profit-take mocks, RPC bleed). Parked for a future cleanup (not #5).
- **In-flight swap reservation race** (stables snapshot vs swap settle). Parked; steady-state invariants pinned in #3 tests.
- `**current_price_usd` operator hygiene** (NEW from Cleanup #3 part 2). Fallback is now a true floor; stale fallbacks above true spot will OVERSTATE TOTAL. Operator-facing reminder: refresh `followed_equities.json` fallback prices periodically (no automation yet; candidate for v2.9 if drift becomes visible).
- `**WMATIC_ALPHA` / `WETH_ALPHA` / `WBTC_ALPHA` blocklist** is operator-managed in `.xsignal_blocked_symbols`. No code change planned unless trading restarts on them.

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

## Append log (side-chat reports come here)



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

