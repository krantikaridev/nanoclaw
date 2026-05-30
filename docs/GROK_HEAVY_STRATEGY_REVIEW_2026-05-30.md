# Grok Heavy strategy review — 2026-05-30

> **Source:** Operator ran Grok Heavy adversarial review before leave (~30 May IST).  
> **Use with:** `docs/OPERATOR_CODE_FREEZE_2026-05-30.md`, `MASTER_BRAINSTORM.md`, `AI_CONTEXT.md`.  
> **VM state at review:** `bf849af7` · ~$131 TOTAL · ~$18 stables · ~85% WETH · session **−1.04%** · `control.json` **paused=true** + `operator_pause_lock=true` (operator leave).

**Operator note on Grok Day 1:** Grok suggested `nanopnl --reset-session` — **do not reset session baseline** unless operator explicitly asks; current anchor is the 48h-green measurement target.

**Copy trading:** Codified in **`docs/COPY_TRADING_AUDIT.md`** — run **`nanocopyaudit`** on VM; do not use token contracts in `followed_wallets.json`.

**Monitoring in code (May 2026):** Operator playbooks from §F and the 7-day plan are encoded as **`nanodeploy`** (pull+verify), **`nanodiag`**, **`nano48h`**, and **`scripts/unpause_readiness.py`** — no repeated copy/paste after `bash scripts/nanobot_aliases.sh --install`.

---

## A. Diagnosis (max 15 bullets)

- **Root cause of no sustained 48h green session PnL**: Precedence + defensive_pause + FE runway logic create conflicting states. X-SIGNAL PLAN SELECTED or rotation_priority can fire while `Risk=HIGH` / `defensive_pause` / `buy_size_multiplier=0.00` blocks execution (documented in AI_CONTEXT.md incidents). Result: capital slowly drains on FE-heavy book without the high-edge rotation that was intended to rescue it. Session resets and nanopnl baselines become meaningless when the engine is fighting itself.

- **FE runway is too late and too narrow**: Trim logic only activates below ~$15 stables and only when WMATIC cannot rebuild buffer. At current ~$18 stables / ~85% WETH FE leg (user snapshot), `USDC→EQUITY` or X-SIGNAL BUYs are still permitted above the threshold. This is the exact overweight incident pattern described in AI_CONTEXT.md (post-WMATIC rotation: stables ~$13, FE ~89%, continued USDC→WETH pressure).

- **Blocklist footgun is live**: User states all symbols blocked + `HONOR_FULL_BLOCKLIST=false` (or equivalent) → blocks ignored. Recent commit bf849af7 added “blocklist honor flag”, but if the flag defaults false or is not wired into `determine_trade_decision` / X-signal path, the protection is cosmetic. This is a config-time invariant violation.

- **followed_wallets.json is almost certainly misconfigured for copy trading**: The JSON contains what appear to be token contract addresses (USDT, USDC, WMATIC, etc.) rather than high-conviction trader wallets. User already suspects this. `polycopy` / copy_trading.py therefore either does nothing useful or pulls garbage. This explains why “USDC copy → polycopy” in precedence never delivered edge.

- **X-SIGNAL is static JSON, not live wallet copy**: `followed_equities.json` has fixed `signal_strength` (WMATIC_ALPHA 0.92, WETH 0.87, WBTC 0.83, LINK 0.81) and `min_signal_strength` floors. No on-chain position monitoring of followed wallets, no real-time conviction refresh. “~2% MIN_NET_EDGE after gas” gate is applied only on entry; exits are softer. Static signals + gas protection = long periods of blocked high-conviction entries while low-edge main WMATIC loop still churns or defensive_pause freezes everything.

- **Polygon DEX at $131 seed has brutal gas/slippage drag relative to edge**: Even on low-gas days, a round-trip (approve + swap) plus quote slippage on small size easily consumes 1–3%+ of notional for anything but the most liquid pairs. With cooldowns (global 4min, per-asset 30min) and one-swap-per-cycle constraint, realistic fills/day are low. Rough breakeven estimate: need ≥4–6 high-quality fills/day with ≥1.5–2.5% net edge after all costs just to overcome drag + opportunity cost of capital sitting in FE. Current setup (FE concentration + frequent defensive blocks) makes positive expectancy unlikely in the observed regime.

- **Loss-cut is off and profit-take is after X-signal in precedence**: This ordering + FE overweight means the bot prefers to add to the concentrated leg rather than cut or rotate out when risk is elevated. `evaluate_take_profit` only runs after protection but before or after X-signal depending on rotation_priority_detector.

- **Small-trade bypasses exist**: AI_CONTEXT incidents document `$4.5` trades firing despite `MIN_TRADE_USD=22` in .env because of hardcoded `_HIGH_CONVICTION_WMATIC_MAX_USD = 4.50`. This leaks capital on micro edges that cannot overcome gas.

- **POL gas buffer / approve crashes are recurring**: Multiple crash-loop incidents on `_force_max_approval` with POL ~0.025 when approve cost ~0.05. No robust pre-flight POL top-up or min-POL guard before approval path. Bot dies exactly when it most needs to act.

- **PnL reporting vs ground truth gaps**: nanopnl / real_cron.log TOTAL vs Polygonscan/MetaMask (Polygon tab) divergences noted repeatedly (e.g., $10+ gaps after LINK buys). FE_USD spot cache (bf849af7) helps but fallback pricing in followed_equities.json and dual-USDC handling still create “what the bot said” vs custody truth mismatches. Session % becomes noisy.

- **Copy quality controls and wallet performance weighting are present in .env but irrelevant if followed_wallets.json is garbage**. `COPY_BASE_EXPECTED_EDGE_PCT`, `COPY_GAS_EDGE_MULTIPLIER`, `COPY_MIN_EFFECTIVE_TRADE_AFTER_GAS_USD` exist but feed from bad data.

- **One-swap-per-cycle + parallel strategy evaluation creates priority inversion**: Multiple strategies can evaluate, but only one executes. When X-signal and main WMATIC both want action, the documented precedence helps, but defensive_pause and gas gates can starve the intended path.

- **Operational load is mismatched to 25% energy / full-time job**: `nano_watch`, frequent `nanorestart`, manual session resets, log grepping for “FE STABLE RUNWAY / PLAN SELECTED / Risk=”, and Cursor/Grok thread switching consume disproportionate hours for negative or flat expectancy.

- **No sustained 48h green because the system is optimized for “don’t blow up” rather than “capture edge when it exists”**. Protection is strong (good), but the positive edge paths (X-signal rotation, clean USDC copy) are frequently gated or misconfigured.

- **Capital is too small for meaningful rotation without concentration or excessive turnover**. $131 with 85% in one FE leg means any material reallocation is either tiny (gas dominates) or swings book composition dramatically.

---

## B. 7-day plan (hour-budgeted for ~25% energy)

**Explicit goal**: Deliver at least one clean 48h session PnL ≥ 0% (ideally two) by end of week, with FE share pulled back toward 50–60% and no defensive_pause vs plan-selected conflicts. Treat this as binary data point for the 30 Jun go/no-go.

**Day-by-day (max one code change per day, rest ops/monitoring)**:

| Day | Hours | Focus |
|-----|-------|--------|
| **1** (leave day) | 2–3h ops | Stop drain: honor blocklist, pause entries (`control.json`), audit `followed_wallets.json`, `nano_watch`. **No session reset.** |
| **2** | 2–3h | **Code #1:** FE-heavy BUY guard (`fe_share > 0.55` AND `stables < $40` → block USDC→EQUITY). |
| **3** | 2h ops + 1h review | Validate blocklist end-to-end; refresh FE fallback prices; tighten X-SIGNAL net edge. |
| **4** | 2–3h | **Code #2 (if needed):** Kill WMATIC small-trade bypass; min POL before approve. |
| **5** | 2h | Ops: target 24h clean window; deliberate trim if still FE-heavy. |
| **6** | 2–3h | First 48h green measurement; no code if flat/green. |
| **7** | 1–2h | Retrospective; update AI_CONTEXT; prep 30 Jun decision. |

**What must STOP immediately**: USDC→EQUITY or X-SIGNAL BUY when fe_share >55% and stables <$40. Any trade < MIN_TRADE_USD effective. Ignoring blocklist. Running with `followed_wallets.json` in its current state.

**What must START**: Explicit FE composition guard + trim priority. One primary venue (Polygon spot only). Strict session baseline discipline. `nano_watch` as primary monitoring.

---

## C. Multi-venue sequencing (leverage-first)

| Rank | Venue | Capital | Dev weeks | Edge honesty | Next step |
|------|-------|---------|-----------|--------------|-----------|
| 1 | **Polygon spot** | deployed | 0 | Low–medium after gas | **Only live venue until 2+ weeks green** |
| 2 | **Polymarket** | $200–500+ | 2–4 paper | High variance | Paper adapter only |
| 3 | **CEX perps** | $500–2000+ | 3–6 | Better liq, funding/liq risk | Defer (India ops/tax) |
| 4 | **Hyperliquid** | $300–1000 | 4+ | High if sized well | Too complex now |
| 5 | **India F&O** | high | many | Poor retail systematic | Do not pursue 6 mo |

**Conclusion:** Stay Polygon-only until repeatable 48h green + FE concentration under control.

---

## D. Copy / X / LLM strategy

- **Copy famous X wallets on-chain?** Only after audit + tiny sizing. Pick by verifiable on-chain PnL, low FE overlap, gas-followable frequency, transparent thesis. Size 5–8% per wallet max; weekly manual review. Start 1–2 wallets in paper.

- **Grok/LLM role:** Advisory + `control.json` writer only — never direct execution gate. PhotonBull = intelligence feed through precedence/gas/sizing/blocklist.

- **Do NOT automate (30–60 days):** Live X ingestion; auto-updating `signal_strength` in JSON; precedence/risk changes without tests; tax/reporting blind automation.

---

## E. Go / no-go vs SaaS/content (30 Jun)

**Pass:** ≥3 clean 48h sessions PnL ≥ 0% (ideally +1–2%) in final 2 weeks of June; FE ≤65% most of time; no plan-vs-pause conflicts; validated followed_* files; <4–5 h/week operator time; written positive expectancy estimate.

**Fail:** Any missing + capital decay / concentration spiral / config footguns.

**If fail → ONE pivot:** **Content** (X + YouTube / HiTalent) over SaaS — lower capital risk, batchable, uses wife’s audience; SaaS burns remaining 25% energy. Park bot in preserve-capital + collect-data mode.

---

## F. Concrete diffs (Cursor side chats — ranked)

1. **ENV / nanoup preserve + enforce `X_SIGNAL_HONOR_FULL_BLOCKLIST`** — log effective flag every cycle.
2. **FE-heavy BUY guard** — block USDC→EQUITY when `fe_share > 0.55` AND `stables < $40`; force trim toward runway target.
3. **`followed_wallets.json` audit / replace or disable** — **`docs/COPY_TRADING_AUDIT.md`** + `nanocopyaudit`.
4. **Default `NANOUP_AUTOSTASH=1` + POL pre-flight** before approve path.
5. **Polymarket paper adapter** — read-only, no wallet touch.

---

## G. Red team (48h loss paths)

- FE concentration + adverse WETH move before trim calibrates.
- Gas/RPC spike blocks needed rotation; micro leakage continues.
- Toxic wallet/signal fires during guard gap.
- POL exhaustion mid-trim (recurring pattern).
- Operator fatigue / missed plan-vs-pause conflict 12–24h.
- “Green” 48h from luck on 1–2 fills; expectancy still marginal at $131.

**Brutal truth:** Flat-to-down still highest probability for 7–14 days unless FE guard + blocklist + followed files fixed and X-signal/main conflicts eliminated. Fix plumbing or park.

---

## Cursor synthesis (next session workflow)

1. Read this file + `OPERATOR_CODE_FREEZE_2026-05-30.md` + latest VM snapshot.
2. Merge Grok **F** with freeze backlog §6 — **max 2 side chats** when freeze lifts.
3. Operator runs Grok again only if book composition or commit hash changed materially.
4. **Copy trading audit** (operator tonight): **`nanocopyaudit`** — see **`docs/COPY_TRADING_AUDIT.md`**.
