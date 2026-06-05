# Infra automation backlog — multi-VM, cloud-agnostic deploy

**Status:** Active roadmap (P0–P3 scripts local; VM+wallet tomorrow).  
**Goal:** One-command **stage vs dev** provisioning — not Oracle-specific; maximize **free tier** (2× Oracle + other clouds).  
**Dev env economics:** [`DEV_ENV.md`](DEV_ENV.md) — **~$50 experimental**, not $80–90 (that was 24/7 lab soak).

## Problem today

| Pain | Current state |
|------|----------------|
| Manual VM setup | SSH, `git clone`, venv, `.env` by hand |
| Oracle lock-in | Paths/snippets assume one Ubuntu VM |
| Two-wallet model | Stage `0x05eF…` vs lab wallet — easy to mix `.env` |
| Deploy friction | `nanoup` fails on dirty tree; stash dance; no greenfield script |
| Free tier | 2 Oracle VMs — need **generic** recipe for GCP/AWS/Azure free tiers too |

## Target end state

```bash
# From laptop (any OS) — spin ephemeral dev VM
./scripts/dev_bootstrap.sh \
  --host 92.4.73.239 \
  --key ~/.ssh/ssh-key-2026-03-15.key \
  --branch V4-play \
  --seed-usd 50 \
  --secrets ~/.nanoclaw/secrets.dev.env \
  --role dev

# Remote ops (only IP + key vary)
./scripts/nanoremote.sh --host 92.4.73.239 --key ... logs
./scripts/nanoremote.sh --host 92.4.73.239 --key ... nano12h
./scripts/nanoremote.sh --host 92.4.73.239 --key ... diag

# Teardown when done (wallet keeps on-chain funds)
./scripts/dev_destroy.sh --host 92.4.73.239 --key ...
```

**Roles:**

| Role | Branch | Tag | Wallet | Capital |
|------|--------|-----|--------|---------|
| **stage** | `V2` | `v2-stage-2026-06-05` | `0x05eF…` | ~$130 (24/7) |
| **dev** | `V4-play` | — | same or new | **~$50** experimental, ephemeral VM |

## Sprint phases (when back)

### P0 — Highest ROI (do first — saves time every day)

- [x] `docs/DEV_ENV.md` — dev capital, 48h gate, secrets
- [x] **`scripts/nanoremote.sh`** — single command: `logs | nano12h | nano8h | diag | shell` via SSH (replaces 3-step ssh+cd+activate)
- [x] `~/.nanoclaw/config.yaml` on laptop: `stage_host`, `dev_host`, `ssh_key` — template: [`infra/config.yaml.example`](../infra/config.yaml.example)

### P0b — Document & inventory (2h)

- [x] `docs/VM_ROLES.md` — stage vs dev table
- [x] `.env.dev.example` — `STAGE_SEED_USD=50`, dual-window on, play budget on, `NANOCLAW_ROLE=dev`
- [x] `scripts/dev_preflight.sh` — SSH, python3, git, RPC probe (`--dry-run`, `--skip-remote`)

### P1 — Ephemeral dev bootstrap (1 day)

- [x] `scripts/dev_bootstrap.sh` — cloud-agnostic SSH deploy (`--dry-run`):
  - create user dir `~/.nanobot/workspace/nanoclaw`
  - `git clone` / `git pull` branch
  - `python3 -m venv .venv` + `pip install -r requirements.txt`
  - merge `secrets.dev.env` → VM `.env` (never commit)
  - `crontab` snippet for `clean_swap.py` (dev: easy disable on destroy)
  - `~/.local/bin` nano shims
- [x] `scripts/dev_destroy.sh` — stop cron, optional wipe `~/.nanobot/workspace/nanoclaw`, **keep wallet**
- [x] `--cloud generic` only first; Oracle/GCP = same script + optional cloud-init YAML

### P2 — Secrets & role file (4h)

- [x] `~/.nanoclaw/secrets.dev.env` pattern — [`infra/secrets.dev.env.example`](../infra/secrets.dev.env.example) + [`docs/VM_ROLES.md`](VM_ROLES.md)
- [x] `NANOCLAW_ROLE=stage|dev` in `.env` — `nanodeploy` prints role in banner
- [x] Block `nanodeploy` via `scripts/deploy_role_guard.py` (dev+V2, stage+V4, V4+stage wallet)
- [ ] GitHub Secrets (optional): `DEV_SSH_KEY`, `DEV_HOST`, `POLYGON_PRIVATE_KEY_DEV` for Actions bootstrap

### P3 — Cloud-init templates (1 day)

- [x] `infra/cloud-init/generic.yaml` — ubuntu user, swap off, python3/git
- [x] `infra/cloud-init/oracle-ubuntu.yaml` — same as generic (Oracle = generic Ubuntu)
- [x] `infra/cloud-init/README.md` — paste into Oracle / GCP / AWS user-data

### P4 — CI smoke (optional)

- [ ] GitHub Action: `v3_pre_deploy_check.sh` + V4-play pytest on push
- [ ] No secrets in CI; compile + unit only

### P5 — Free-tier map

| Provider | Free shape | Use |
|----------|------------|-----|
| **Oracle** | 2× AMD micro | **stage** + **lab** |
| **GCP** | e2-micro | spare lab / RPC-only |
| **AWS** | t2/t3.micro 12mo | cold standby |
| **Azure** | B1s | dev pytest runner |

## V4 engineering priority (PnL > 0)

| Priority | Item | Why |
|----------|------|-----|
| **P0** | **`nanoremote.sh`** + dev bootstrap | Operator time; no manual SSH dance |
| **P1** | **Prove V4-play on $50 dev** | Dual-window + play budget stops Jun-3 class losses |
| **P2** | **Merge V4 gates → stage** | Highest trading ROI after 48h dev soak |
| **P3** | Refactor `swap_executor.py` | Maintainability; **not** blocking PnL if gates work |
| **Defer** | More symbols, copy trading | Widens risk before gates proven |

**Code quality today:** `ruff` + pytest in CI (`.github/workflows/ci.yml`); **~79% coverage** per `AI_CONTEXT.md`; run `python scripts/update_coverage_history.py` for snapshot. No standalone HTML report — `coverage.xml` from CI. **Weakest:** `swap_executor.py` size/monolith.

## Non-goals (this sprint)

- Terraform full IaC (later if needed)
- Auto-fund wallets / on-chain deploy keys via cloud APIs
- Merging `V4-play` → stage without **48h dev soak** (see `DEV_ENV.md`)

## Operator handoff (Jun 5 break)

- **Stage:** `V2` @ `v2-stage-2026-06-05`, **paused**, window **~−3.5%**, **pause_exec PASS**, **0 churn today**
- **Optional before break:** MetaMask **$12–20 WETH→USDC** (manual); keep bot paused
- **When back:** spin **lab VM** on `V4-play`; run this backlog **P0→P1**

## References

- [`docs/AGENT_SPRINT_PROMPTS_V4.md`](AGENT_SPRINT_PROMPTS_V4.md)
- [`docs/ROTATION_PLAYBOOK.md`](ROTATION_PLAYBOOK.md)
- [`scripts/deploy_vm_safe.sh`](../scripts/deploy_vm_safe.sh)
- [`scripts/v3_pre_deploy_check.sh`](../scripts/v3_pre_deploy_check.sh)
