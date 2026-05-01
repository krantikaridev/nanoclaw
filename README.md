# Nanoclaw v2 (Polygon)

Nanoclaw is a risk-first trading bot for Polygon that executes real swaps and is designed to be **100% `.env` driven**, unit-testable, and resilient to RPC/gas volatility.

## Quick start

- **Install deps**: create/activate your Python environment and install requirements for this repo (project-specific).
- **Configure env**: copy `.env.example` to `.env` (never commit secrets).
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
./scripts/pre_commit_gate.ps1
```

Checklist reference:

- `docs/CLEAN_STATE_CHECKLIST.md`

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

