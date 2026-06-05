# Infra automation backlog — multi-VM, cloud-agnostic lab deploy

**Status:** TODO when operator returns from break.  
**Goal:** One-command **stage vs lab** provisioning — not Oracle-specific; maximize **free tier** (2× Oracle + other clouds).

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
# From laptop (any OS)
./scripts/lab_bootstrap.sh \
  --cloud oracle|gcp|aws|generic \
  --host lab-vm.example \
  --wallet 0xNEW… \
  --branch V4-play \
  --seed-usd 80 \
  --dry-run

# On VM after bootstrap (idempotent)
nanodeploy --role lab   # or --role stage
```

**Roles:**

| Role | Branch | Tag | Wallet |
|------|--------|-----|--------|
| **stage** | `V2` | `v2-stage-2026-06-05` | `0x05eF…` (frozen until merge gate) |
| **lab** | `V4-play` | — | new wallet per VM |

## Sprint phases (when back)

### P0 — Document & inventory (2h)

- [ ] `docs/VM_ROLES.md` — stage vs lab table, never-share `.env` rule
- [ ] `.env.lab.example` — minimal template (`STAGE_SEED_USD=80`, dual-window on, play budget on)
- [ ] `scripts/lab_preflight.sh` — SSH check, python3, git, disk, RPC probe

### P1 — Generic bootstrap script (1 day)

- [ ] `scripts/lab_bootstrap.sh` — cloud-agnostic SSH deploy:
  - create user dir `~/.nanobot/workspace/nanoclaw`
  - `git clone` / `git pull` branch
  - `python3 -m venv .venv` + `pip install -r requirements.txt`
  - copy `.env` from operator-supplied secrets file (never commit)
  - `crontab` snippet for `clean_swap.py`
  - `~/.local/bin` nano shims
- [ ] `--cloud generic` only first; Oracle/GCP = same script + optional cloud-init YAML

### P2 — Secrets & role file (4h)

- [ ] `~/.nanoclaw/secrets.env` on VM (gitignored pattern documented)
- [ ] `NANOCLAW_ROLE=stage|lab` in `.env` — `nanodeploy` prints role in banner
- [ ] Block `nanodeploy` if `WALLET=` matches known stage address on `role=lab` branch mismatch

### P3 — Cloud-init templates (1 day)

- [ ] `infra/cloud-init/generic.yaml` — ubuntu user, docker optional, swap off
- [ ] `infra/cloud-init/oracle-ubuntu.yaml` — same as generic (Oracle = generic Ubuntu)
- [ ] `infra/cloud-init/README.md` — paste into Oracle / GCP / AWS user-data

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

## Non-goals (this sprint)

- Terraform full IaC (later if needed)
- Auto-fund wallets / on-chain deploy keys via cloud APIs
- Merging `V4-play` → stage without 48h lab gate

## Operator handoff (Jun 5 break)

- **Stage:** `V2` @ `v2-stage-2026-06-05`, **paused**, window **~−3.5%**, **pause_exec PASS**, **0 churn today**
- **Optional before break:** MetaMask **$12–20 WETH→USDC** (manual); keep bot paused
- **When back:** spin **lab VM** on `V4-play`; run this backlog **P0→P1**

## References

- [`docs/AGENT_SPRINT_PROMPTS_V4.md`](AGENT_SPRINT_PROMPTS_V4.md)
- [`docs/ROTATION_PLAYBOOK.md`](ROTATION_PLAYBOOK.md)
- [`scripts/deploy_vm_safe.sh`](../scripts/deploy_vm_safe.sh)
- [`scripts/v3_pre_deploy_check.sh`](../scripts/v3_pre_deploy_check.sh)
