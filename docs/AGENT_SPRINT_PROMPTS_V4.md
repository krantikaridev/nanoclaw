# Agent sprint — V4-play (lab only)

**Do not `nanodeploy` V4-play to stage wallet `0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6`.**

| Item | Value |
|------|--------|
| **Branch** | `V4-play` (fork from `V2` @ `738222ed`) |
| **Stage (Track A)** | `V2` @ tag `v2-stage-2026-06-05` — paused, no experiments |
| **Lab (Track B)** | New VM + new wallet, `STAGE_SEED_USD=80` |

## Shipped on V4-play (`d6c6d627`)

| Module | Purpose |
|--------|---------|
| `external_layer/dual_window_unpause.py` | `auto_unpause` requires **8h AND 12h** window PASS |
| `nanoclaw/play_budget.py` | Max **2** entry fills/UTC day when `TOTAL < $200` |
| `nanoclaw/negative_window_x_signal_cap.py` | Cap X-Signal at **$10** when 12h window **< 0%** |
| `docs/ROTATION_PLAYBOOK.md` | Safe per-swap caps by book size |

## Lab VM bootstrap

```bash
git clone https://github.com/krantikaridev/nanoclaw.git && cd nanoclaw
git checkout V4-play && git pull
# .env: new WALLET, STAGE_SEED_USD=80, drpc-first RPC
# EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW=true (default on branch)
bash scripts/v3_pre_deploy_check.sh
NANOUP_AUTOSTASH=1 nanodeploy
```

## Merge to stage gate

1. Lab **48h**: ≤ 4 fills/day, `nano8h` + `nano12h` PASS stable  
2. Parent merges `V4-play` → `V2`, full pytest  
3. Stage `nanodeploy` only after operator sign-off  

See [`ROTATION_PLAYBOOK.md`](ROTATION_PLAYBOOK.md) for swap caps.
