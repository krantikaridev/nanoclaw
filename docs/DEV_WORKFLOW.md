# Nanoclaw development workflow

Use this so code review feedback and operator habits stay consistent across sessions.

Role ownership and collaboration loop are defined in **`docs/OPERATING_MODEL.md`**.

## Before commit

1. **`python -m ruff check .`**
2. **`python -m compileall -q .`**
3. **`python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml`**
4. **`git diff --stat`** — scope matches intent.
5. **Completion discipline** — for every behavior/config change, update tests + docs + `.env.example` in the same PR.

Windows shortcut: `powershell -ExecutionPolicy Bypass -File .\scripts\pre_commit_gate.ps1`  
(or `.\scripts\pre_commit_gate.cmd`)

## Environment files

- **`.env`** is gitignored; **`.env.example`** is the canonical template for safe keys and stage policy.
- **Secrets first**, **new non-secret tuning at the bottom** of `.env` to avoid merge corruption when agents append lines.
- **Wallet key**: set **`POLYGON_PRIVATE_KEY`** (preferred); legacy **`PRIVATE_KEY`** is still read as fallback.
- **Hook enforcement (required on VM, recommended local)**: run `git config core.hooksPath .githooks` so pre-commit and pre-push secret guards are always enforced; `nanoup` and `nanopush` now auto-apply this setting.
- **Git side rejection**: keep CI required for protected branches; CI runs `scripts/check_committed_secrets.py --all-tracked` and rejects forbidden `.env` paths / secret-looking assignments on PRs to protected branches.
- **Future hardening TODO**: apply platform settings checklist in `docs/REPO_HARDENING.md` (branch protection + required checks + push protection).
- **RPC + fallbacks + gas-probe extras**: see **`docs/ENV_RPC.md`** (primary `RPC` / `RPC_URL` / `WEB3_PROVIDER_URI`, built-in public list, and optional `RPC_FALLBACKS`).
- **ROI / PnL labels** (`nanostatus` / `nanopnl`): **`PORTFOLIO_BASELINE_USD`** — use **`0`** (template default) or leave unset for automatic baseline; set a positive number to pin starting capital (`modules/baseline.py`). See `.env.example` and `docs/ENV_RPC.md`.

### Refresh `.env.example` from a live `.env` (strip secrets)

From repo root (`.venv` active):

```bash
python scripts/nanoenv_example.py --write
git diff .env.example
```

Optional shell alias:

```bash
nanoenv () { python3 "${NANOCLAW_ROOT:-.}/scripts/nanoenv_example.py" "$@"; }
```

Always review the diff: the script redacts known secret keys but does not reorganize sections—hand-edit for cohesion if needed.

## Deploy / VM

- **`scripts/nanoup.sh`**: kill bot → `git pull --ff-only` → `nohup python clean_swap.py`.  
  Bash helper: `nanoup() { bash "${NANOCLAW_ROOT:-$HOME/.nanobot/workspace/nanoclaw}/scripts/nanoup.sh"; }`
- **`nanostatus`** / **`nanopnl`** / **`show_balances.py`**: portfolio uses on-chain totals + optional `PORTFOLIO_BASELINE_USD` / `portfolio_baseline.json`.
- Full reusable deploy sequence (including one-time exceptional `.env.example` -> `.env` reset path): **`docs/readme-vm-update.md`**.
- Alias bootstrap and fallback commands are documented in **`docs/readme-vm-update.md`**.

### VM quick runbook (ops-safe)

- Runtime files (`portfolio_history.csv`, `real_cron.log`) are expected to change while bot runs.
- For the canonical VM update/restart flow, use **`docs/readme-vm-update.md`**.

### Fallback router policy (current)

- Primary executor remains 1inch (when API key works).
- Fallback executor is **Uniswap V3 SwapRouter** (`exactInputSingle`, fee tier `3000`).
- Fallback quoting is **also Uniswap V3 Quoter** (`quoteExactInputSingle`) to keep quote/execution protocol-consistent.
- For `USDC_TO_*` fallback trades, code auto-selects spendable token source (`USDC` vs `USDC_NATIVE`) before approval/swap.

## Policy constants (stage, 2026-05)

Enforced in code + `.env.example`: **`COPY_TRADE_PCT=0.28`**, **`TAKE_PROFIT_PCT=5.0`**, **`STRONG_SIGNAL_TP=12.0`**, signal thresholds **`0.80`**, fixed **$12–$20** per signal via `fixed_copy_trade_usd` (not separate `COPY_TRADE_SIZE_USD` env keys).

## Where logic lives

- Thin entry: `clean_swap.py`
- Runtime / balances / baseline: `modules/runtime.py`, `modules/baseline.py`
- X-Signal orchestration: `modules/signal.py`, `nanoclaw/strategies/signal_equity_trader.py`
- Optional Grok/Telegram: `modules/agent_layer.py` (`NANOCLAW_GROK_ENABLED`, `GROK_API_KEY` / `XAI_API_KEY`, `TELEGRAM_*`)

See **`AI_CONTEXT.md`** on branch **`V2`** for backlog and incidents.
