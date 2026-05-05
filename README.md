# Nanoclaw v2 (Polygon)

Nanoclaw is a risk-first trading bot for Polygon that executes real swaps and is designed to be **100% `.env` driven**, unit-testable, and resilient to RPC/gas volatility.

For operators and agents, **`AI_CONTEXT.md`** on branch **`V2`** is the authoritative process and backlog; this README is the onboarding surface.

**Development workflow** (commit gate, env sync, deploy helpers): **`docs/DEV_WORKFLOW.md`**.
**Reusable VM deploy runbook** (including exceptional `.env.example` -> `.env` path): **`docs/readme-vm-update.md`**.
**Roles and collaboration loop** (Grok/Human/Cursor): **`docs/OPERATING_MODEL.md`**.

## Who Does What

- Strategy/priority: **Grok + Human**.
- Major implementation: **Cursor** (local code + tests + docs).
- Push/deploy/runtime validation: **Human** (VM/stage), then **Grok + Human** decide next delta.
- Full role contract: **`docs/OPERATING_MODEL.md`**.

## Quick commands (`nano*` convention)

| Command | What it does |
|---------|----------------|
| `nanoup` | Safe update + restart (recommended); repo script: **`scripts/nanoup.sh`** |
| `nanostatus` | PnL/status report from `real_cron.log` via `scripts/pnl_report.py` |
| `nanopnl` | Alias of `nanostatus` for quick PnL view |
| `nanobot` | Live log stream (`tail -f real_cron.log`) |
| `nanorestart` | Safe restart flow: `nanoup && nanostatus` |
| `nanokill` | Stop the bot |
| `nanoattach` | Attach to live bot logs |
| `nanodaily` | Daily health snapshot: balances, bypass/cooldown/protection counters, commit, TEST_MODE |
| `nanoenvsync` | Sync `.env.example` from `.env` (secrets blanked) and verify drift/coverage |
| `nanoenvcheck` | Verify `.env.example` key coverage and drift vs sanitized `.env` |
| `nanoenvstage` | Run env sync/check and stage `.env.example` for commit |
| `nanocommit` | Enforce repo hooks, then run `git commit` |
| `nanopush` | Secret check + env sync/check + stage `.env.example`, then `git push` |
| `python scripts/nanoenv_example.py --write` | Redact secrets from `.env` → refresh `.env.example` (review diff before commit) |

**`sprintmon`** is not in this repo; use **`nanostatus`** / **`nanopnl`** for quick health + PnL and **`nanobot`** / **`nanoattach`** for live logs.

**USDC top-up for X-Signal equity** is handled inside the bot (`try_x_signal_equity_decision`), not as a separate shell alias. Configure `X_SIGNAL_USDC_SAFE_FLOOR` and `X_SIGNAL_AUTO_USDC_TARGET` in `.env` (see `.env.example`).

### Safe Update Flow (use this every time)

```bash
nanorestart
```

If the VM has intentional local edits, run with auto-stash restore:

```bash
NANOUP_AUTOSTASH=1 nanorestart
```

If aliases are missing on VM (`nanoup: command not found`), use direct script fallback once:
`NANOUP_AUTOSTASH=1 bash scripts/nanoup.sh`, then install aliases via
`scripts/nanobot_aliases.sh --install && source ~/.bashrc` (details in `docs/readme-vm-update.md`).
`--install` also installs standalone command shims into `~/.local/bin` (`nanostatus`, `nanopnl`, etc.) so commands work in fresh shells without manual re-source.

### Stop / restart

```bash
nanokill
nanoup
```

## Quick start

- **Install deps**: create/activate your Python environment and install requirements for this repo (project-specific).
- **Configure env**: copy `.env.example` to `.env` (never commit secrets).
  - X-Signal equity now includes proactive USDC top-up before any BUY decision when USDC drops below `X_SIGNAL_USDC_SAFE_FLOOR`. The top-up target is `X_SIGNAL_AUTO_USDC_TARGET`.
- **Run**:

```bash
python clean_swap.py
```

## Tests

```bash
python -m pytest
```

## Release safety

Run the pre-commit gate before commit/push:

```bash
./scripts/pre_commit_gate.sh
```

PowerShell (Windows):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pre_commit_gate.ps1
```

Windows shortcut (avoids policy friction each run):

```powershell
.\scripts\pre_commit_gate.cmd
```

Checklist reference:

- `docs/CLEAN_STATE_CHECKLIST.md`

## Coverage tracking (in-repo)

Generate and persist a coverage snapshot (for humans + AI agents):

```bash
python scripts/update_coverage_history.py
```

This command:

- runs test suite with coverage
- writes raw JSON to `artifacts/coverage/coverage.json`
- appends critical-module summary to `docs/COVERAGE_HISTORY.md`

For ROI-first iteration, review deltas in:

- `docs/COVERAGE_HISTORY.md`

## Key scripts

- `clean_swap.py`: main orchestrator (decision + gas protection + execution)
- `swap_executor.py`: approve + swap executor (direction-based)
- `nanoclaw/utils/gas_protector.py`: RPC fallback + safe gas/POL checks (builder pattern)
- `nanoclaw/strategies/usdc_copy.py`: USDC copy strategy (builder + gas-protected)

## Configuration

- **Template**: `.env.example`
- **Do not commit**: `.env` (contains secrets)
- Optional local override file: `.env.local` (loaded after `.env` when present)

### Required addresses (Polygon)

- `WALLET`
- `USDT`, `USDC`, `WMATIC`
- `ROUTER`

### ABI configuration

ABIs are stored in-repo under `nanoclaw/abi/` and loaded by `constants.py`. You can override paths via:

- `ERC20_ABI_PATH`
- `ROUTER_ABI_PATH`
- `GET_AMOUNTS_OUT_ABI_PATH`

## Notes

- Only **one on-chain swap** is executed per cycle (nonce safety), even if multiple strategies evaluate in parallel.

## VM deploy (safer flow)

Avoid `git stash -a && git pull && git stash pop` for normal deploys.
Use clean-tree deploy instead:

```bash
./scripts/deploy_vm_safe.sh V2
```

This script enforces:

- clean working tree
- fast-forward pull
- local verification (`compileall` + `pytest`)
- controlled bot restart

## Stage pre-pull safety (accounts.db)

Before removing `accounts.db`, verify it is safe:

```bash
./scripts/check_accounts_db.sh
```

Policy:

- zero rows -> safe to delete
- non-zero rows -> investigate before delete

## VM fix script env target

`scripts/fix_vm.sh` now writes gas overrides into `.env` by default.
If your runtime uses `.env.local` overrides, point it explicitly via `NANOCLAW_ENV_PATH`.
Override env file path if needed:

```bash
NANOCLAW_ENV_PATH=/path/to/.env ./scripts/fix_vm.sh
```

## Docker Compose

Use `.env` as the single runtime env file:

```bash
cp .env.example .env
docker compose up -d --build
```

## Share runtime artifacts for AI review

Create a non-secret analysis bundle:

```bash
./scripts/package_runtime_artifacts.sh
```

Then upload the generated `artifacts/share/*.tar.gz` to Drive and share the link.

## Wallet safety

Do not run two trading bots with the same wallet/private key at the same time.
Use one writer bot per wallet (second instance only in dry-run/read-only mode).

## Maintainer & agent context

Operators and assistants should anchor session state on branch **`V2`** using **`AI_CONTEXT.md`** — process, backlog, and handoff rules (`docs/NEW_THREAD_PROTOCOL.md`). Keep dummy or test-era rows out of `portfolio_history.csv` when reconciling telemetry; **`scripts/clean_dummy_data.sh`** trims rows to cycles with logged successful swaps (`real_cron.log`).

