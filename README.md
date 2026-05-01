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

## Docker Compose (stage/prod split)

Create env files locally (ignored by git):

```bash
cp .env.example .env.stage
cp .env.example .env.prod
```

Run stage:

```bash
NANOCLAW_ENV_FILE=.env.stage docker compose up -d --build
```

Run production:

```bash
NANOCLAW_ENV_FILE=.env.prod docker compose up -d --build
```

