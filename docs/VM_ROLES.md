# VM roles — stage vs dev

Two-track model: **stage** stays frozen on V2 until **dev** proves V4-play over 48h.

## Role table

| | **stage** | **dev** |
|---|-----------|---------|
| **Branch** | `V2` @ tag `v2-stage-2026-06-05` | `V4-play` |
| **Wallet** | `0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6` | Same or **separate** dev wallet (prefer separate) |
| **Capital** | ~$130 (24/7) | ~$50 experimental ([`DEV_ENV.md`](DEV_ENV.md)) |
| **`STAGE_SEED_USD`** | `158` (stage book) | `50` |
| **`NANOCLAW_ROLE`** | `stage` | `dev` |
| **VM** | `92.4.73.239` (24/7 Oracle) | Ephemeral lab VM (respins OK) |
| **Path** | `~/.nanobot/workspace/nanoclaw` | Same layout |
| **Cron** | Always on | On while testing; **off** on destroy |

## V4-play gates (dev only)

See [`ROTATION_PLAYBOOK.md`](ROTATION_PLAYBOOK.md). Dev `.env` overlay: [`.env.dev.example`](../.env.dev.example).

- Dual-window unpause: 8h **and** 12h PASS
- Play budget: ≤ 2 entry fills / UTC day when TOTAL < $200
- X-Signal cap $10 when 12h window < 0%

## Secrets layout

| File | Machine | Commit? |
|------|---------|---------|
| `~/.nanoclaw/config.yaml` | Operator laptop | **Never** — copy from [`infra/config.yaml.example`](../infra/config.yaml.example) |
| `~/.nanoclaw/secrets.dev.env` | Operator laptop | **Never** — copy from [`infra/secrets.dev.env.example`](../infra/secrets.dev.env.example) |
| `~/.nanobot/workspace/nanoclaw/.env` | VM | **Never** — merged by `dev_bootstrap.sh` |
| `.env.dev.example` | Repo | Yes — dev tuning overlay (no secrets) |
| `.env.example` | Repo | Yes — full template |

`dev_bootstrap.sh` copies `.env.dev.example` → VM `.env`, then overlays `secrets.dev.env` keys.

## Deploy guards (`nanodeploy`)

Blocked combinations (see `scripts/deploy_role_guard.py`):

- `NANOCLAW_ROLE=dev` + branch `V2`
- `NANOCLAW_ROLE=stage` + branch `V4-play`
- Branch `V4-play` + stage wallet `0x05eF…`

## Operator commands

```bash
# Laptop config (once)
cp infra/config.yaml.example ~/.nanoclaw/config.yaml
cp infra/secrets.dev.env.example ~/.nanoclaw/secrets.dev.env   # fill keys

# Preflight (no wallet spend)
./scripts/dev_preflight.sh --role dev --dry-run

# Spin lab VM (tomorrow — needs funded wallet in secrets.dev.env)
./scripts/dev_bootstrap.sh --role dev --branch V4-play --seed-usd 50 \
  --secrets ~/.nanoclaw/secrets.dev.env

# Remote ops
./scripts/nanoremote.sh --role dev nano12h
./scripts/nanoremote.sh --role dev logs

# Teardown (wallet keeps on-chain funds)
./scripts/dev_destroy.sh --role dev
```

## Stage read-only (while paused)

```bash
./scripts/nanoremote.sh --role stage diag
./scripts/nanoremote.sh --role stage nano12h
```

Do **not** unpause, `nanodeploy`, or run pytest on stage until operator sign-off.

## References

- [`DEV_ENV.md`](DEV_ENV.md) — capital, 48h gate
- [`INFRA_AUTOMATION_BACKLOG.md`](INFRA_AUTOMATION_BACKLOG.md) — sprint phases
- [`AGENT_SPRINT_PROMPTS_V4.md`](AGENT_SPRINT_PROMPTS_V4.md) — V4-play scope
