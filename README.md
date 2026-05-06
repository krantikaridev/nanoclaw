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
| `nanoup` | Safe update + restart (recommended), including `.env` apply from `.env.example` with secret/runtime-key preserve; ends with **`nanohealth`** (Polygon RPC + chain `137`); repo script: **`scripts/nanoup.sh`** |
| `nanohealth` | **`python scripts/nanohealth.py`**: RPC gate via **`connect_web3()`**; exit `1` if unhealthy |
| `nanostatus` | PnL/status report from `real_cron.log` via `scripts/pnl_report.py` (forwards CLI flags, e.g. `--reset-session`) |
| `nanopnl` | PnL view with current balance, baseline/session %, and 24h delta (best-effort from `portfolio_history.csv`) |
| `nanobot` | Live log stream (`tail -f real_cron.log`) |
| `nanorestart` | **`nanoup`** then **`nanohealth`** then **`pnl_report`** (forwards flags where applicable) |
| `nanokill` | Stop the bot |
| `nanoattach` | Attach to live bot logs |
| `nanodaily` | Daily health snapshot: **LOOKBACK** table (current log total vs `portfolio_history.csv` at 1h…~1m horizons), baseline/session PnL, bypass/cooldown/protection counters, commit, TEST_MODE |
| `nanoenvsync` | Sync `.env.example` from `.env` (secrets blanked) and verify drift/coverage |
| `nanoenvcheck` | Verify `.env.example` key coverage and drift vs sanitized `.env` |
| `nanoenvstage` | Run env sync/check and stage `.env.example` for commit |
| `nanocommit` | Enforce repo hooks, then run `git commit` |
| `nanopush` | Secret check + env sync/check + stage `.env.example`, then `git push` |
| `python scripts/nanoenv_example.py --write` | Redact secrets from `.env` → refresh `.env.example` (review diff before commit) |
| `python scripts/nanoenv_apply.py --write` | Apply latest `.env.example` keys into `.env` while preserving secret/runtime keys |

**`sprintmon`** is not in this repo; use **`nanohealth`** before trusting PnL, then **`nanostatus`** / **`nanopnl`** and **`nanobot`** / **`nanoattach`** for live logs.
Session baseline can be reset manually with `nanopnl --reset-session` (or `nanostatus --reset-session` / `nanorestart --reset-session`).
`scripts/pnl_report.py` now prefers the runtime line **`WALLET TOTAL USD`** (`STABLE_USD` = USDT+USDC when present, **WMATIC** = token qty — not USD) for `nanostatus`/`nanopnl`/`nanodaily`; then legacy live snapshots, then `MANUAL CORRECT BALANCE`. If authoritative stables are ~0 but TOTAL is large, the report flags **RPC read suspect** (compare wallet UI / Polygonscan). **`--daily-summary`** adds **LOOKBACK** (past **`portfolio_history.csv`** vs now), a one-line **Unicode sparkline** of **`total_value`**, and a **UTC hourly** close / Δ table (decision support—not a substitute for on-chain reconcile). **`--lookback`** accepts **`1h,4h,24h,1d,1w,1m`**; **`nanodaily`** passes a multi-window list by default.

**USDC top-up for X-Signal equity** is handled inside the bot (`try_x_signal_equity_decision`), not as a separate shell alias. Configure `X_SIGNAL_USDC_SAFE_FLOOR`, `X_SIGNAL_AUTO_USDC_TARGET`, `X_SIGNAL_AUTO_USDC_TOPUP_ENABLED`, `X_SIGNAL_AUTO_USDC_MIN_SWAP_USD`, and `X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS` in `.env` (see `.env.example`). Top-up prefers `USDT -> USDC` and falls back to `WMATIC -> USDC`. On-chain USDC reads retry before fallback (`X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS`). AUTO-USDC logs now include per-attempt pre/post/target telemetry and a short failure backoff to reduce repeated retry loops.
**USDC copy quality controls** now include gas-aware filtering and per-wallet performance weighting. Configure `COPY_BASE_EXPECTED_EDGE_PCT`, `COPY_GAS_EDGE_MULTIPLIER`, `COPY_MIN_EFFECTIVE_TRADE_AFTER_GAS_USD`, `COPY_MIN_MARGINAL_TRADE_USD`, and the `COPY_WALLET_PERFORMANCE_*` keys to tune allocation penalties for poor recent wallet performance.

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
`--install` also installs standalone command shims into `~/.local/bin` (`nanohealth`, `nanostatus`, `nanopnl`, etc.) so commands work in fresh shells without manual re-source.

### Stop / restart

```bash
nanokill
nanoup
```

## Quick start

- **Install deps**: create/activate your Python environment and install requirements for this repo (project-specific).
- **Configure env**: copy `.env.example` to `.env` (never commit secrets).
  - Signing key resolution is centralized and env-only: `POLYGON_PRIVATE_KEY` (preferred), then `PRIVATE_KEY` (legacy).
  - If neither key is present, startup exits with an actionable error before swaps/approvals run.
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

- **Template**: `.env.example` (committed; sanitized defaults and comments)
- **Runtime**: `.env` (not committed; secrets and machine values)
- **`nanoup`** merges `.env.example` → `.env`, preserving secrets and RPC-related keys only (see `nanoclaw/env_sync.py`). Other keys take template values on each deploy—**promote VM tuning by updating `.env.example`**, then pull/`nanoup`, or edit `.env` after `nanoup` knowing the next `nanoup` may reset non-preserved keys.
- **External layer**: operator/agent control JSON is **`control.json`** at the repo root (written via `external_layer/control.py`). Each live bot cycle loads it in **`modules/swap_executor.main`** and passes overrides into **`determine_trade_decision`** (paused / copy-trade %); see **`external_layer/README.md`** for scope.
- VM steps (RPC placeholders, **`MAX_GWEI`**, probe snippet): **`docs/readme-vm-update.md`**. Send USDC on Polygon to the bot (**beginner**): **`docs/OPERATOR_SEND_USDC_POLYGON.md`**.

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

`scripts/fix_vm.sh` writes gas overrides into `.env` by default. To target another file:

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

