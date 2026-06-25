# Prod VM migration plan — stage → fresh $1k capital

**Status:** Planning only (no prod deploy scripts yet).  
**Prerequisite:** Stage stable on merged **V2** (V4-play gates soaked), `pause_exec` PASS, dual-window unpause validated.

## Goals

1. **Isolate prod** from stage wallet (`0x05eF…`) and stage experiments.
2. **Fresh $1k book** with conservative caps while reusing proven V2 + V4-play tooling.
3. **No surprise deploys** — role guards, separate secrets, separate VM.

---

## Key differences: stage vs prod

| Dimension | **Stage** (today) | **Prod** (target) |
|-----------|-------------------|-------------------|
| **Wallet** | `0x05eF…` (~$130, bleeding history) | **New wallet** — fund ~$1k USDC + ~$2–5 POL |
| **`NANOCLAW_ROLE`** | `stage` | `prod` (new role — extend `deploy_role_guard.py`) |
| **`STAGE_SEED_USD`** | `158` (historical book) | `1000` (session / reserve math anchor) |
| **Branch** | `V2` @ tagged snapshot | `V2` (same code; tag prod deploy e.g. `v2-prod-YYYY-MM-DD`) |
| **Play budget** | On if TOTAL < $200 | **On** initially (`PLAY_BUDGET_MAX_FILLS_PER_UTC_DAY=2`) until book > $200 |
| **Per-swap cap** | $8–10 (rotation playbook) | **$10** max entry; tighten to $8 if window < 0% |
| **Dual-window unpause** | Enabled post V4-play merge | **Required** (`EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW=true`) |
| **Unpause hysteresis** | Optional on stage | **Recommended ON** (6 ticks) to reduce whipsaw on $1k book |
| **Monitoring** | `nanodiag`, `nano12h`, manual | Same + **`nano_watch.sh`** cron; Telegram alerts |
| **VM lifetime** | 24/7 Oracle | 24/7 dedicated Oracle (or second free-tier) |
| **Destroy policy** | Never | Never — unlike dev ephemeral VMs |

### Risk parameters (prod `.env` overlay)

Use `.env.example` as base; prod-specific overrides (no secrets in repo):

```bash
NANOCLAW_ROLE=prod
STAGE_SEED_USD=1000
PLAY_BUDGET_ENABLED=true
PLAY_BUDGET_MAX_FILLS_PER_UTC_DAY=2
PLAY_BUDGET_TOTAL_USD_CEILING=200
EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW=true
EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED=true
EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS=6
X_SIGNAL_NEGATIVE_WINDOW_CAP_ENABLED=true
X_SIGNAL_NEGATIVE_WINDOW_MAX_TRADE_USD=10
FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD=10
MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_NOTIONAL_USD=10
ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL=false   # until prod has 48h clean book
```

### Rotation universe

- **`followed_equities.json`:** WMATIC, WETH, LINK, **AAVE**, **UNI** (WBTC stays blocklisted — quoter issues).
- **`.xsignal_blocked_symbols` on prod:** start with `WMATIC_ALPHA` (operator WMATIC stack) + `WBTC_ALPHA`; open WETH, LINK, AAVE, UNI for diversity.
- Revisit blocklist after first week using `rotation:` line from `nano_green`.

---

## Reusing V4-play tooling for prod

| Tool | Stage use | Prod use |
|------|-----------|----------|
| **`dev_bootstrap.sh`** | Spin ephemeral dev VM | **Pattern only** — copy to future `prod_bootstrap.sh` (same cloud-init, different role/secrets) |
| **`nanoremote.sh`** | `--role stage` read-only while paused | Add `--role prod` host in `~/.nanoclaw/config.yaml` |
| **`deploy_role_guard.py`** | Blocks V4-play → stage wallet | Extend: `prod` cannot use stage wallet; `stage` cannot deploy to prod host |
| **`dev_preflight.sh`** | Dev dry-run | Run with `--role prod --dry-run` before first fund |
| **`infra/cloud-init/`** | Dev VM user-data | Same `oracle-ubuntu.yaml` for prod VM |
| **`scripts/nanodeploy.sh`** | Stage deploy (frozen) | Prod deploy after guard + tag |

Suggested **`~/.nanoclaw/config.yaml`** addition:

```yaml
prod_host: <new-oracle-ip>
prod_wallet: <0xNEW…>   # comment only — real wallet in secrets
```

---

## Secrets management

### Recommendation: hybrid (not GitHub-only)

| Secret | Where | Why |
|--------|-------|-----|
| `POLYGON_PRIVATE_KEY`, `ANKR_RPC_KEY`, Telegram | **`~/.nanoclaw/secrets.prod.env`** on operator laptop (chmod 600) | Same pattern as `secrets.dev.env`; never in git |
| Bootstrap injection | `scp` via future `prod_bootstrap.sh` → VM `~/.nanoclaw/secrets.env` | One-time; merged into `.env` on VM |
| **GitHub Secrets** | CI-only: SSH key, prod host IP, **masked** deploy token | Use for **automated** `nanodeploy` / health checks — not for day-to-day key editing |
| **VM `.env`** | Generated on VM; gitignored | Source of truth at runtime |

**Do not** reuse stage private key on prod. **Do not** store prod key in GitHub unless using OIDC + short-lived secrets with audit.

Copy template:

```bash
cp infra/secrets.dev.env.example ~/.nanoclaw/secrets.prod.env
# fill WALLET=<new>, POLYGON_PRIVATE_KEY, ANKR_RPC_KEY, TELEGRAM_*
```

---

## Suggested folder / file structure

```
~/.nanoclaw/                          # operator laptop (never commit)
├── config.yaml                       # stage_host, dev_host, prod_host, ssh_key
├── secrets.dev.env
└── secrets.prod.env

~/.nanobot/workspace/nanoclaw/        # prod VM (same as stage layout)
├── .env                              # merged: .env.example + prod overlay + secrets
├── .env.prod.example                 # (future) prod tuning only — no secrets
├── control.json                      # gitignored runtime
├── followed_equities.json
├── .xsignal_blocked_symbols          # prod blocklist
├── .runtime/                         # fe_usd_spot_cache, control backup
├── real_cron.log
└── portfolio_history.csv

infra/
├── config.yaml.example
├── secrets.dev.env.example
├── secrets.prod.env.example          # (future) WALLET= placeholder for prod
└── cloud-init/oracle-ubuntu.yaml
```

---

## Migration phases (operator order)

### Phase 0 — Stabilize stage (current)

1. Deploy asset expansion + `pause_exec` fix to stage (paused).
2. Confirm `nano12h` / `pause_exec: PASS` after unpause trial on dev VM first.

### Phase 1 — Prod prep (no trading)

1. Create **new wallet**; fund test POL only; add to `secrets.prod.env`.
2. Extend `deploy_role_guard.py` + `nanoremote.sh` for `prod` role.
3. Add `prod_host` to `config.yaml`.
4. Spin VM via cloud-init (manual or scripted); clone repo @ `V2` tag.
5. Run `v3_pre_deploy_check.sh`, pytest, `unpause_readiness.py` — **paused**, cron off.

### Phase 2 — Fund and soak

1. Fund **~$1k USDC** + **~$3 POL** on prod wallet.
2. `nanopnl --reset-session` on prod; verify Polygonscan vs `WALLET TOTAL USD`.
3. Keep **`paused=true`** + `operator_pause_lock=true` for 24h while history accumulates.
4. Enable external layer; verify dual-window + play budget in logs (still paused).

### Phase 3 — Go live

1. Remove `operator_pause_lock`; let **auto_unpause** when 8h **and** 12h PASS.
2. Monitor 48h: ≤ 4 fills/day, no `pause_exec` FAIL, no discipline breach.
3. Tag deploy: `v2-prod-YYYY-MM-DD`.

### Phase 4 — Stage wind-down (optional)

- Keep stage **paused** as read-only canary or decommission after prod proves stable 2 weeks.

---

## Pre-flight checklist (prod)

- [ ] New wallet funded; stage wallet not in prod `.env`
- [ ] `NANOCLAW_ROLE=prod` + deploy guard passes
- [ ] `followed_equities.json` includes AAVE + UNI; WBTC blocked
- [ ] Dual-window + play budget env set
- [ ] `pause_exec` PASS on dev soak with unpause → trade → repause cycle
- [ ] Telegram / `nano_watch` configured
- [ ] `operator_pause_lock=true` until deliberate go-live

---

## References

- [`VM_ROLES.md`](VM_ROLES.md) — stage vs dev (extend for prod)
- [`DEV_ENV.md`](DEV_ENV.md) — 48h gate, secrets layout
- [`ROTATION_PLAYBOOK.md`](ROTATION_PLAYBOOK.md) — caps by book size
- [`INFRA_AUTOMATION_BACKLOG.md`](INFRA_AUTOMATION_BACKLOG.md) — bootstrap automation backlog
