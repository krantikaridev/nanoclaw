# Dev environment — ephemeral VM, small capital, same logic as stage

**Dev** tests one aspect (rotation, unpause gates, play budget) on **V4-play**. **Stage** (`0x05eF…`, `V2`, 24/7) stays frozen until dev soak + merge.

## Capital — you fund the **delta**, not another $130

Stage **~$130** stays untouched. Dev is a **separate wallet** with **scaled seed** — same code paths, same **%** gates, smaller **$** caps.

| Profile | Total wallet | USDC (trading) | POL (gas) | `STAGE_SEED_USD` | Runtime |
|---------|--------------|----------------|-----------|------------------|---------|
| **Experimental (recommended)** | **~$50–55** | **~$48–50** | **~$1–2** | **50** | Ephemeral VM, cron on while testing, **off when destroyed** |
| **Comfortable** | **~$65–70** | **~$60** | **~$2–3** | **60** | Same |
| ~~Old “lab $80–90”~~ | ~~$85+~~ | For 24/7 soak only | ~~$10 POL~~ | ~~80~~ | Stage-like; **not required** for short dev runs |

### Why not $10 POL on dev?

- **$10 POL** was a **24/7 stage** buffer (AUTO-POL, many cron cycles, Ankr retries).
- Polygon swaps cost **fractions of $0.01–0.05** in POL at low gwei.
- **Ephemeral dev** (hours, not weeks): **1–2 POL (~$0.10–0.20)** is enough for dozens of test swaps.
- Stage already has **~11 POL** from history — don’t copy that to dev.

### Minimum that still exercises rotation

- **2× $8 fills** (play budget) + **$20 stables floor** after buy → **~$36** stables needed at peak stress.
- **$48–50 USDC** start + **$1 POL** → **~$50 total** wallet funding.
- High-stable rotation needs **≥ $30 stables** — achievable after first cycle with $50 book.

**Same advantage as stage:** identical env keys (scaled), same modules — only `STAGE_SEED_USD`, `WALLET`, and `PLAY_BUDGET_*` differ.

## 48h gate — what it means (not “pass 8h once”)

**Soak test** before merging **V4-play → V2 → stage deploy**:

| Metric | Pass criteria (over **48 consecutive hours**) |
|--------|-----------------------------------------------|
| **Fills** | **≤ 4** `EXEC SUCCESS` / UTC day (avg) |
| **8h window** | Mostly **PASS** when unpaused; no long FAIL streaks without pause |
| **12h window** | Same |
| **pause_exec** | **No FAIL** (no EXEC after pause marker) |
| **Dual-window** | No unpause unless **both** 8h and 12h PASS (V4-play) |
| **No breach** | No burst of 4× X-Signal like Jun 3 |

One `nano12h PASS` tick is **not** the gate. The gate is **stable behavior over 2 days** on **dev**, then operator sign-off.

## Secrets — where they live

| Secret | Store | Never |
|--------|-------|-------|
| `POLYGON_PRIVATE_KEY`, `ANKR_RPC_KEY`, Telegram | **Operator laptop:** `~/.nanoclaw/secrets.dev.env` (chmod 600) | Git, Slack, chat |
| Bootstrap injection | `scp secrets.dev.env` → VM `~/.nanoclaw/secrets.env` via `dev_bootstrap.sh` | Commit to repo |
| **GitHub Secrets** | OK for **CI deploy** (Actions SSH to VM, write `.env` once) | Browsing in logs; use masked vars |
| **Same wallet dev+stage** | Allowed for **dev** experiments if you accept state coupling — **prefer separate** dev wallet |

GitHub Secrets are **right for automated spin-up/teardown**; local `secrets.dev.env` is **right for manual** until P1 bootstrap exists.

## Ephemeral dev VM lifecycle (target)

```bash
# Laptop config (once)
cp infra/config.yaml.example ~/.nanoclaw/config.yaml
cp infra/secrets.dev.env.example ~/.nanoclaw/secrets.dev.env   # fill WALLET + keys

# Dry-run locally (no VM/wallet)
./scripts/dev_preflight.sh --role dev --dry-run --skip-remote
./scripts/dev_bootstrap.sh --role dev --dry-run
./scripts/dev_destroy.sh --role dev --dry-run

# Tomorrow: cloud-init (infra/cloud-init/README.md) → preflight → bootstrap
./scripts/dev_preflight.sh --role dev
./scripts/dev_bootstrap.sh --role dev --branch V4-play --seed-usd 50 --secrets ~/.nanoclaw/secrets.dev.env
./scripts/nanoremote.sh --role dev logs
./scripts/nanoremote.sh --role dev nano12h
./scripts/dev_destroy.sh --role dev --wipe   # optional; wallet keeps on-chain funds
```

**Same wallet across VM respins:** yes — fund wallet once; each new VM gets fresh clone + same `secrets.dev.env`.

## Today (no VM fund): test on stage VM without trading

```bash
git clone https://github.com/krantikaridev/nanoclaw.git ~/nanoclaw-v4-test
cd ~/nanoclaw-v4-test && git checkout V4-play && python3 -m venv .venv && source .venv/bin/activate
pip install -q -r requirements.txt
python -m pytest tests/unit/test_dual_window_unpause.py tests/unit/test_play_budget.py -q
bash scripts/v3_pre_deploy_check.sh
```

Stage bot keeps running; no `.env` change on `~/.nanobot/workspace/nanoclaw`.
