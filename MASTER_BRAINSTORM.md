# Master Brainstorm — Operator ↔ AI working memory

> **Purpose.** This file is the working memory of the **master chat session**: the long-running operator/AI brainstorming loop. It is **not** project documentation (that's `AI_CONTEXT.md`) and **not** roadmap (that's `ROADMAP.md`). It tracks open threads, decisions, and handoffs to **side chats** that do the actual coding.
>
> **Style:** append-only. Strike-through (not delete) when something is superseded. Every entry is dated. Side-chat handoff prompts live here verbatim for traceability.
>
> **Two-chat model:**
> - **Master chat** (this one) — strategy, triage, evidence collection, handoff-prompt drafting, side-chat review/merge gate. No code edits.
> - **Side chats** — implement one cleanup / one feature / one fix. Open with a handoff prompt from this file. Push to `origin/V2`. Close.
>
> When master gets too long, fork it with the **"Master chat continuation" prompt** at the bottom of this file. The new master reads this doc as its sole context.

---

## Current focus (top of stack)

- ~~**Cleanup #3 — IN PROGRESS**~~ ✅ MERGED to `origin/V2` 2026-05-26: commits `9f85cbcb` (POL_USD visibility), `9abb0881` (LINK MTM fallback floor), `9adb388d` (stables drift regression tests), `76946ea3` (WBTC balance-read noise gate). Test gate 47 → 52 in the canonical 4-file set (+ 9 new tests in adjacent files, 61 total across the runtime test surface). See [Append log](#append-log-side-chat-reports-come-here) for the side-chat report.
- **Next**: re-run scaling math (operator priority) once a few clean cycles confirm wallet-vs-bot within $1 in steady state. Then Cleanup #4 (pre-existing 9 test failures + in-flight swap reservation race).
- **Operator north star:** trustworthy **+ve net PnL** on stage → increase seed → maximize **capital rotation** (X-Signal path) → scale toward **~$100k** per release train.

## Recent merged work (commits on `origin/V2`)

| Commit | Title | Side chat | Status |
|---|---|---|---|
| `76946ea3` | Cleanup #3 (4/4): suppress `BALANCE READ FAILED` spam after first per-token log | Cleanup #3 side chat | merged 2026-05-26 |
| `9adb388d` | Cleanup #3 (3/4): pin stables drift invariants at `get_balances()` surface | Cleanup #3 side chat | merged 2026-05-26 |
| `9abb0881` | Cleanup #3 (2/4): treat `current_price_usd` as a true FALLBACK FLOOR for FE_USD | Cleanup #3 side chat | merged 2026-05-26 |
| `9f85cbcb` | Cleanup #3 (1/4): surface POL_USD in WALLET TOTAL USD for operator parity | Cleanup #3 side chat | merged 2026-05-26 |
| `30fb17b9` | Cleanup #2: harden `_force_max_approval` against startup-crash landmine | (other thread) | merged + deployed to VM 2026-05-26 |
| `fb5eac6e` | Cleanup #1: route WALLET TOTAL USD through one helper | (other thread) | merged + deployed to VM 2026-05-26 |
| `bbfa05d9` | Enhance FE_USD fallback + diagnostics for unquoted assets | this master | merged + deployed |
| `ca6ca24c` | Lower WBTC min notional + tighten slippage | this master | merged + deployed |

## Open questions / parked threads

- **Seed-capital scaling** (~$120 → $1k → $25k → $100k). Operator priority (2026-05-26): +ve PnL first, then seed + rotation velocity. **Parked for sizing decisions** until Cleanup #3 lands ✓ and P0 validation runs on wallet-accurate books — master can re-open scaling math now that POL_USD is visible, LINK MTM is fallback-floored, stables invariants pinned, and WBTC log noise is gated. Verify wallet-vs-bot match within $1 in steady state on a few clean cycles before scaling.
- **Pre-existing 9 test failures** (outdated profit-take logic, mock signature mismatches, live RPC bleed into mock-only tests). Confirmed unchanged by Cleanup #3 (re-run against the pre-#3 tree). Deferred from Cleanup #1; still assigned to Cleanup #4.
- **In-flight swap reservation race in stables accounting** (NEW from Cleanup #3 part 3). Steady-state arithmetic in `get_balances()` is correct (regression tests now pin USDC dedup + USDT fresh-read). The 2026-05-26 ±$8.56 stables drift coincided with `tx 1de9409c` settling mid-cycle — most plausibly a balance-read snapshot at a non-deterministic point relative to swap settlement. Candidate fix for Cleanup #4: optional debounced re-read after `approve_and_swap` returns a tx hash, before the next `WALLET TOTAL USD` emission. Out of scope for #3 per acceptance criterion A.
- **`current_price_usd` operator hygiene** (NEW from Cleanup #3 part 2). Fallback is now a true floor; stale fallbacks above true spot will OVERSTATE TOTAL. Operator-facing reminder: refresh `followed_equities.json` fallback prices periodically (no automation yet; candidate for v2.9 if drift becomes visible).
- **`WMATIC_ALPHA` / `WETH_ALPHA` / `WBTC_ALPHA` blocklist** is operator-managed in `.xsignal_blocked_symbols`. No code change planned unless trading restarts on them.

## Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-26 | Adopt master/side-chat split; this file is the seam | Master threads were exceeding usable context; side chats need surgical scope |
| 2026-05-26 | `WBTC_ALPHA` in blocklist; balance-read noise gate deferred to Cleanup #3 | Trading impact zero; log impact medium |
| 2026-05-26 | `compute_authoritative_total_usd` is the **only** sanctioned source of `WALLET TOTAL USD` | Cleanup #1 (`fb5eac6e`). Side chats must not re-introduce regex parsing. |
| 2026-05-26 | `_force_max_approval` wrapper no longer passes `force=True` | Cleanup #2 (`30fb17b9`). Closes May 24 crash-loop landmine. |
| 2026-05-26 | `current_price_usd` in `followed_equities.json` is a **fallback floor**, not authoritative | Live on-chain MTM preferred; fallback only when quote returns 0 |

---

## Cleanup #3 handoff prompt

> Copy the block below verbatim into a new chat. The new chat is a **side chat** — it implements, tests, commits, pushes, and reports back here.

```
ROLE: Implementer for nanoclaw Cleanup #3. You are a side chat spawned by the master chat session. Your job is to fix the PnL accounting drift symptoms below, push to origin/V2, and report back a one-paragraph summary + commit hashes.

REPO STATE (2026-05-26 13:32 IST):
- Branch: V2
- HEAD: 30fb17b9 (Cleanup #2 — _force_max_approval hardened)
- Origin/V2 deployed to VM; bot is live and trading
- Authoritative TOTAL helper: `modules.runtime.compute_authoritative_total_usd(balances)` — see commit fb5eac6e. Do NOT bypass it; fix sources that feed it.

THE SYMPTOM (verified against MetaMask screenshot 2026-05-26 ~13:36 IST):
- Wallet TOTAL: $121.33
- Bot TOTAL:    $111.08  (via `nanopnl` → "RUNTIME WALLET TRUTH (in-process compute_authoritative_total_usd)")
- Gap:          $10.25  ← suspiciously equals the size of the LINK_ALPHA buy (tx 1de9409c) that fired in the same cycle.

COMPONENT BREAKDOWN:
| Bucket  | Wallet                                              | Bot          | Delta            |
|---------|-----------------------------------------------------|--------------|------------------|
| Stables | $52.24 (USDC.e $37.50 + USDC native $4.26 + USDT $10.48) | $60.80       | +$8.56 OVER      |
| WMATIC  | $14.50 (156.571 WMATIC)                             | $14.50       | 0 (good)         |
| LINK    | $53.74 (5.676 LINK × $9.43)                         | ~$35.78 (implied) | -$17.96 SHORT |
| POL     | $0.85 (9.177 POL)                                   | $0           | -$0.85 SHORT     |
| TOTAL   | $121.33                                              | $111.08      | -$10.25          |

THREE LIKELY BUGS (verify each before fixing):

(1) POL NOT INCLUDED IN TOTAL
   - Native POL gas balance is $0.85 in wallet but contributes $0 to bot TOTAL.
   - Investigate `modules/runtime.py` `get_balances()` and `compute_authoritative_total_usd`.
   - Decide: include POL in TOTAL (probably yes — it's spendable capital just like WMATIC) OR
     explicitly document why it's excluded and emit an operator log line so the gap is visible.
   - Likely fix: add a `pol_usd` field to Balances, populate from `w3.eth.get_balance(WALLET) × POL_USD_PRICE`.

(2) LINK MTM UNDERCOUNTED BY ~$18
   - 5.676 LINK at fallback price $9.43 = $53.52. Bot has $35.78.
   - $35.78 / $9.43 ≈ 3.79 LINK — suspiciously close to "pre-trade balance" (5.676 - 10.25/9.43 = 4.59).
   - Possible causes:
     (a) `get_balances()` snapshots LINK balance BEFORE the trade settles, then computes TOTAL post-trade-debit-pre-trade-credit (race).
     (b) On-chain quote returns a value lower than $9.43/LINK (stale fallback overriding fresh quote? or vice versa?).
     (c) `_followed_equity_tokens_usdt_usd` exits early on a symbol mismatch.
   - Add a unit test that pins: balance B × max(live_quote_usdt, fallback_usd) = expected_fe_usd.
   - Verify `FE_USD UNQUOTED` diagnostic from commit `bbfa05d9` fires when it should.

(3) STABLES OVERCOUNT BY ~$8.56
   - Bot says USDC=$31.53; wallet shows USDC.e=$37.50 + native USDC=$4.26 = $41.76. Bot is $10.23 short on USDC.
   - Bot says USDT=$29.27; wallet shows USDT=$10.48. Bot is $18.79 OVER on USDT.
   - Net stables overcount = +$8.56 (overcount on USDT > undercount on USDC).
   - Likely cause: stale snapshot caching from a previous cycle, OR USDT balance being read from a wrong contract / decimals, OR a swap-in-flight reservation being double-counted.
   - Verify both USDC variants (USDC.e at 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174 and native USDC at 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359) are summed exactly once.
   - Verify USDT is read fresh per cycle, not cached.

ALSO IN SCOPE (smaller, related):

(4) WBTC BALANCE-READ NOISE GATE
   - `.xsignal_blocked_symbols` contains `WBTC_ALPHA` but `real_cron.log` still shows:
     `[nanoclaw-av] BALANCE READ FAILED | token=0x1BFd6703…6C834E | BadFunctionCallOutput`
   - The blocklist gates trading, not inventory reads. Add a single-warn-then-suppress wrapper OR
     short-circuit balance reads for symbols in the blocklist.
   - Choose whichever is more surgical. Do not refactor surrounding code.

OUT OF SCOPE (defer to Cleanup #4):
- The 9 pre-existing test failures (profit-take logic, mock signatures, live RPC bleed).
- Any change to trading strategy, slippage, or signal thresholds.
- Any refactor of the swap_executor module beyond the minimum needed for the fixes above.

DISCIPLINE (workspace rules, non-negotiable):
- Karpathy guidelines: minimum diff, no speculative features, no adjacent "improvements", surgical changes only.
- task-completion-discipline.mdc: add/update unit tests for every behavior change; update AI_CONTEXT.md "Today's learnings"; update .env.example if you add env knobs (state explicitly if no change needed).
- Read at least once before editing.
- Run targeted tests before commit. Green-gate baseline:
  pytest tests/unit/test_runtime_authoritative_total.py tests/unit/test_runtime_inventory_mtm.py tests/unit/test_pnl_report.py tests/unit/test_force_max_approval_resilience.py -q
  (currently 47/47 green; new tests should keep total green)

ACCEPTANCE CRITERIA:
A. Wallet TOTAL (from MetaMask) and bot TOTAL (from nanopnl) match within $1 when the wallet is in steady state (no in-flight swaps).
B. Unit test asserts POL is included (or explicitly excluded with a logged reason).
C. Unit test asserts FE_USD = balance × effective_price for held equities, with effective_price = max(live_quote, fallback).
D. Unit test asserts both USDC variants are summed exactly once and not double-counted.
E. WBTC balance-read failures no longer spam logs more than once per process lifetime (or per symbol).
F. AI_CONTEXT.md "Today's learnings" entry documents each fix.
G. Commits follow the Cleanup #1/#2 format (one cleanup item per commit, body explains rationale + tests + env-impact, "Co-authored-by: Cursor <cursoragent@cursor.com>").
H. Push to origin/V2. Report HEAD hash back to master chat.

DELIVERABLE BACK TO MASTER CHAT:
- Commit hash(es) on origin/V2.
- One-paragraph summary of what changed and why.
- Test count delta (e.g. "47 → 53 passing").
- Any new entry to add to MASTER_BRAINSTORM.md "Recent merged work" table.
- Any new parked thread to add to "Open questions".

Start by reading: modules/runtime.py, AI_CONTEXT.md (esp. the FE_USD section + Today's learnings), scripts/pnl_report.py, swap_executor.py (just the WALLET TOTAL USD print site). Then state your plan before coding.
```

---

## Master chat continuation prompt

> Use this when **this master thread** gets too long. Open a fresh chat and paste this block. The new master picks up where this one left off, with `MASTER_BRAINSTORM.md` as its working memory.

```
ROLE: You are the master chat for the nanoclaw bot — operator's brainstorming partner, triage, and side-chat dispatcher. You do NOT write production code in this thread; you draft handoff prompts and review side-chat output.

CONTEXT FILES (read these first, in order):
1. MASTER_BRAINSTORM.md — your working memory; current focus, open threads, decisions log, archived handoff prompts. THIS IS YOUR PRIMARY CONTEXT.
2. AI_CONTEXT.md — project governance, design rules, "Today's learnings" (chronological incident log).
3. ROADMAP.md — directional milestones.
4. .cursor/rules/*.mdc — task-completion-discipline + karpathy-guidelines. Hold side chats to these.

OPERATING MODEL:
- This thread is master. Code edits happen in side chats opened from this thread.
- For each cleanup / feature / fix, draft a handoff prompt and append it to MASTER_BRAINSTORM.md before dispatching. Verbatim, with date.
- When a side chat finishes, update MASTER_BRAINSTORM.md (Recent merged work + Decisions log + Open questions).
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

<!--
Side chats append a block here when they finish. Format:

### YYYY-MM-DD — Cleanup #N — <one-line summary>
- Commits: `<hash>` <title>
- Tests: N → M passing
- Notes: <anything master needs to know>
-->

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
