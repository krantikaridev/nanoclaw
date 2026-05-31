# Agent sprint prompts (May 2026)

Copy one prompt per parallel agent. Parent agent reviews all PRs and runs regression before push.

**Branch:** `V2`  
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

## Parent review checklist (before push)

```bash
python -m pytest tests/unit/test_rpc_probe.py tests/unit/test_operating_reserve.py tests/unit/test_rpc_health.py tests/unit/test_fe_stable_runway_tiered.py -q
python -m pytest tests/unit/test_external_auto_pause.py tests/unit/test_nano_green.py -q
python scripts/rpc_probe.py
python -m compileall -q nanoclaw modules scripts external_layer
```

**VM after push:**
```bash
NANOUP_AUTOSTASH=1 nanodeploy
# Fix Ankr key (operator): ANKR_RPC_KEY in .env → nanohealth ok
STAGE_SEED_USD=132  # optional in .env for reserve floor
grep OPERATING_RESERVE real_cron.log | tail -5
nano12h
python3 -c "import json; print(json.load(open('control.json')))"
```

Expect: session FAIL → **auto_pause** sets `paused=True` within ~30s; reserve floor defers entries at $8.91 stables.
