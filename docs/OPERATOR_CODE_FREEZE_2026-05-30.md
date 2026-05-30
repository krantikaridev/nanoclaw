# Operator code freeze — 2026-05-30 (IST leave → ~7 Jun)

> **Status:** Code freeze on `origin/V2` @ **`bf849af7`**. No side chats until operator returns.  
> **Open new Cursor thread** with: this file + `MASTER_BRAINSTORM.md` + `AI_CONTEXT.md` § Today's learnings 30 May.

---

## 1. Bot health snapshot (2026-05-30 ~14:35 IST)

| Signal | Value | OK? |
|--------|-------|-----|
| Commit | `bf849af7` | ✓ |
| RPC / `nh` | chain 137 green | ✓ |
| TOTAL / MetaMask | ~$130.89 / ~$131 | ✓ (≤$1) |
| Session PnL | **−1.04%** (~−$1.38) | ⚠ not green |
| Stables | $17.91 (~14%) | ⚠ low; FE ~85% |
| Loss-cut | `ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false` | ✓ |
| Catastrophic bleed | stopped (no gas spiral) | ✓ |
| Recent churn | 3× WETH BUY post-deploy (stables $50→$18) | ⚠ |
| **`X_SIGNAL_HONOR_FULL_BLOCKLIST`** | **`false`** (nanoup reset from template) | ✗ footgun |
| Blocklist | all 4 symbols listed | ⚠ ignored when all blocked + honor=false |
| Current cycle behavior | `$9.33` BUY **dust_deferred** (< $10 min) | ✓ accidental brake |
| `clean_swap` in `pgrep` | **not seen** in snapshot (only `control.py`) | ⚠ verify |

### Leave as-is?

**Acceptable for a short break (hours)** if you confirm the trading loop is alive:

```bash
pgrep -af clean_swap.py || { echo "NO BOT — restarting"; nanoup; sleep 30; pgrep -af clean_swap.py; }
```

**Not ideal for days** without:

1. `X_SIGNAL_HONOR_FULL_BLOCKLIST=true` in `.env` **and** add to `ENV_APPLY_PRESERVE_KEYS` (post-freeze task), **or** blocklist only 3 symbols (leave one open).
2. Optional: `nano_watch` running → `nohup bash scripts/nano_watch.sh >> ~/nano_watch.nohup.log 2>&1 &`

**Will session PnL flip green while away?** Unlikely unless WETH mark-up ~1%. Dust defer + blocklist skips reduce further harm.

---

## 2. Honest go / no-go (revised — months of history)

You have **months** on stage (~$130), **~2 months on Cursor**, not a fresh 30-day experiment.

| Question | Answer |
|----------|--------|
| Can automation + LLM + markets **always** make money? | **No guarantee.** Edge must be measured. |
| Has Polygon rotation proven **positive session PnL** at this seed? | **Not yet** (−1% session; long prior churn). |
| Is the project dead? | **Not decided** — infra bleed largely fixed @ `bf849af7`; **expectancy still unproven**. |
| Single focus through **30 Jun**? | **Yes, if** you want a binary answer: **pass P0 bar or pivot** (SaaS / content). |

**P0 pass bar (unchanged):** 7d live · ≥40 swaps · session/net **> +2%** · max DD **< 10%** · books match MetaMask ≤$1.

**Pivot trigger:** By **30 Jun**, session PnL still negative after ≥40 post-`bf849af7` fills **or** DD > 10% → trading bot is **not** your one focused goal; archive stage learnings.

---

## 3. Multi-venue roadmap (not Polygon-only) — leverage-first

**Principle:** Add venues by **edge × capital velocity × implementation cost**, not “everything at once.” Intelligence (LLM, X, signals) is **shared**; execution is **per-venue adapters** under one risk ledger (`external_layer` / `control.json`).

| Priority | Venue / instrument | Why first | Realistic PnL contribution (6 mo, if executed) | Prereq |
|----------|-------------------|-----------|-----------------------------------------------|--------|
| **1** | **Polygon DEX** (current) | Only **proven** execution path | **+0.5–2%/wk** session *if* edge exists | P0 pass @ $130–500 |
| **2** | **Polymarket** (prediction) | Short horizon, capital rotates fast, API/bot patterns exist | **+1–3%/wk** on small bank *high variance* | Legal/geo OK; separate wallet; Phase 3 ROADMAP |
| **3** | **CEX perps** (e.g. Binance) | Leverage + liquidity + fast round-trip | **+2–5%/wk** *or* larger DD | KYC, API keys, liquidation rails — **not** Polygon wallet |
| **4** | **Hyperliquid / on-chain perps** | On-chain leverage, faster than spot DEX | Similar to CEX perps | New executor module |
| **5** | **Indian equities / F&O** | Home market | **Regulatory product** — months of compliance | SEBI/broker — **not** a bot flag |
| **6** | Commodities / options | Tail hedges | Low velocity until infra mature | Defer |

**Compressed timeline (your 1 month ≈ others’ 6 mo)** — leave **30 May → 7 Jun** busy, **~25% energy**:

| Window | Deliverable | PnL expectation |
|--------|-------------|-----------------|
| **30 May – 7 Jun** (leave) | Code freeze; `nano_watch`; confirm P0 on Polygon only | Flat to −2% session; **no new code** |
| **8 – 15 Jun** | Polygon P0 decision; **FE-heavy BUY guard** side chat; preserve `HONOR_FULL_BLOCKLIST` on nanoup | Target session **≥ 0%** 5 days |
| **16 – 22 Jun** | Polymarket **paper** + tiny live adapter (parallel track) | Learning, not income |
| **23 – 30 Jun** | **Go/no-go** + pick **one** second venue OR pivot | Documented expectancy |

**Do not expect** 6-month income from all venues by 30 Jun — expect **Polygon proof + one second venue scoped**.

---

## 4. Operator commands cheat sheet (alias candidates)

All assume: `cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate`

### Daily (2 commands)

| Alias (proposed) | Command today |
|------------------|---------------|
| **`nh`** | Already exists — RPC + health |
| **`np`** / **`nanopnl`** | `nanopnl \| grep -E 'TOTAL\|Stables\|Session PnL\|velocity'` |

### Deploy / restart

| Proposed | Today | Notes |
|----------|-------|-------|
| **`nu`** | `nanoup` | **Post-freeze:** default `NANOUP_AUTOSTASH=1` in `nanoup.sh` |
| **`nr`** | `nanorestart` | pull + health + pnl |
| **`nk`** | `nanokill` | stop bot |

### Snapshot (paste to master chat)

| Proposed | Command |
|----------|---------|
| **`ns`** | See §5 below — writes `~/nanoclaw_snapshot_*.log` |

### Monitor (background)

| Proposed | Command |
|----------|---------|
| **`nw`** | `nohup bash scripts/nano_watch.sh >> ~/nano_watch.nohup.log 2>&1 &` |

### Env fixes (after nanoup wipes them)

```bash
# Must survive nanoup — until added to ENV_APPLY_PRESERVE_KEYS:
grep -q '^X_SIGNAL_HONOR_FULL_BLOCKLIST=true' .env || echo 'X_SIGNAL_HONOR_FULL_BLOCKLIST=true' >> .env
grep -q '^ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false' .env || echo 'ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false' >> .env
```

### WETH floor (local only — gitignored path)

```bash
python3 -c "
import json; p='followed_equities.json'; d=json.load(open(p))
for a in d.get('assets',[]):
    if a.get('symbol')=='WETH_ALPHA': a['current_price_usd']=2000.0
json.dump(d, open(p,'w'), indent=2); print('ok')
"
```

---

## 5. One-shot snapshot script (`ns`)

Save as `~/bin/ns` or run directly:

```bash
cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate
OUT=~/nanoclaw_snapshot_$(date -u +%Y%m%dT%H%M%SZ).log
exec > >(tee "$OUT") 2>&1
echo "SNAPSHOT UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ) IST=$(TZ=Asia/Kolkata date +%H:%M)"
git log -1 --oneline
pgrep -af 'clean_swap|control.py' || echo "WARNING: no clean_swap"
grep -E '^(TEST_MODE|ALLOW_HIGH_RISK|X_SIGNAL_HONOR|FE_STABLE_RUNWAY)=' .env
cat .xsignal_blocked_symbols 2>/dev/null
nanopnl | grep -E 'TOTAL|Stables|Session PnL|velocity'
grep -E 'FE STABLE RUNWAY|EXEC SUCCESS|PLAN SELECTED|Risk=|TRADE SKIPPED|dust_deferred' real_cron.log | tail -20
echo "LOG=$OUT"
```

---

## 6. Post-freeze backlog (first side chat when back)

1. **`ENV_APPLY_PRESERVE_KEYS`:** add `X_SIGNAL_HONOR_FULL_BLOCKLIST`, `FE_STABLE_RUNWAY_*` toggles.
2. **`nanoup.sh`:** default `NANOUP_AUTOSTASH=1` (document in README).
3. **FE-heavy BUY guard:** block `USDC→EQUITY` when `fe_share > 0.55` and `stables < 40` (even if stables > 15).
4. **Aliases:** install `ns`, `nw`, `nu` in `scripts/nanobot_aliases.sh`.
5. **Polymarket adapter** scoping (ROADMAP Phase 4) — only after Polygon P0 trend positive.

---

## 7. New thread handoff prompt

```
ROLE: Master operator for nanoclaw — triage only, no code until operator ends code freeze.

READ FIRST:
1. docs/OPERATOR_CODE_FREEZE_2026-05-30.md (this freeze state)
2. MASTER_BRAINSTORM.md — append log 2026-05-30
3. AI_CONTEXT.md — FE runway, P1 spot cache, blocklist honor

VM: Instance A @ bf849af7 · wallet 0x05eF… · ~$131 TOTAL · session ~−1% · leave until ~7 Jun IST.

OPERATOR GOALS:
- Multi-venue (leverage-first), not Polygon-only long term
- ~25% energy through 30 Jun; binary go/no-go on trading vs SaaS/content
- Easy ops: nh, nanopnl, nanoup without env args

START: Run operator snapshot (§5). Confirm clean_swap alive. Do not reset session baseline unless operator asks.
```

---

## 8. Known footguns (from today's logs)

1. **All symbols in `.xsignal_blocked_symbols` + `HONOR_FULL_BLOCKLIST=false`** → blocks **ignored**; all 4 assets trade again.
2. **`nanoup` resets `X_SIGNAL_HONOR_FULL_BLOCKLIST`** — not on preserve list yet.
3. **`followed_equities.json` local edits** — stash before nanoup; WETH floor 2000 manually.
4. **24h PnL +26%** — CSV sparse anchor; ignore for decisions.
5. **`pgrep clean_swap` empty** — verify bot loop; cron may differ from nohup.
