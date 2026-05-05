# VM Update Runbook (Reusable)

Canonical stage VM deploy flow for branch `V2`. Use this whenever promoting local changes to VM, including release/tag runs.

Role split and decision loop: `docs/OPERATING_MODEL.md`.

## Scope

- Repo path: `~/.nanobot/workspace/nanoclaw`
- Branch: `V2`
- Runtime source of truth: `.env`
- Template source of truth for git: `.env.example` (synced from `.env` via scripts)

## One-time VM alias bootstrap

If `nanoup`/`nanorestart` are missing (`command not found`), add aliases once:

```bash
scripts/nanobot_aliases.sh --install
source ~/.bashrc
```

`--install` also places standalone `nano*` command shims in `~/.local/bin` so commands keep working in new shells without re-sourcing.

Verify aliases are loaded:

```bash
type nanoup
type nanokill
type nanorestart
type nanostatus
type nanodaily
```

`nanostatus`, `nanopnl`, and `nanorestart` now forward CLI flags to `scripts/pnl_report.py` (example: `--reset-session`).
`scripts/pnl_report.py` prefers live balance snapshots (`WALLET BALANCE` + `Real USDT`, then `Real USDT`) and only falls back to `MANUAL CORRECT BALANCE` when live data is not usable.

Verify standalone shims are discoverable on `PATH`:

```bash
command -v nanoup nanostatus nanopnl nanodaily
```

Fallback (no alias required):

```bash
NANOUP_AUTOSTASH=1 bash scripts/nanoup.sh
bash scripts/nanokill.sh
bash scripts/nanorestart.sh
```

## Standard Flow (recommended every time)

1. Local machine (Cursor):
   - Run gates:
     - `python -m compileall -q .`
     - `python -m pytest -q`
   - Commit and push to `origin/V2`.
   - Record hash:
     - `git rev-parse --short HEAD`

2. VM update:
   - `cd ~/.nanobot/workspace/nanoclaw`
   - `NANOUP_AUTOSTASH=1 nanoup`
   - This is preferred because `scripts/nanoup.sh` handles:
     - bot stop/start
     - `git pull --ff-only`
     - dirty runtime files (`portfolio_history.csv`, `real_cron.log`) via autostash

3. VM env parity sync (required before push/tag from VM):
   - `python scripts/nanoenv_example.py --write`
   - `python scripts/verify_env_example_keys.py`
   - `git diff .env.example`

4. Verify deployed code/runtime:
   - `git log --oneline -5`
   - `nanostatus`
   - `nanopnl`
   - `nanopnl --reset-session` (optional: reset session baseline to current total)
   - `./nanodaily`
   - `tail -n 120 real_cron.log`

5. If VM produced tracked changes (for example `.env.example`, docs):
   - `git add .env.example AI_CONTEXT.md docs/readme-vm-update.md`
   - `git commit -m "chore: sync vm env template and runbook references"`
   - `git push origin V2`

## Keepalive (always running after reboot/crash)

If you are not using systemd/supervisor yet, set a minimal cron watchdog:

```bash
crontab -e
```

```cron
@reboot cd ~/.nanobot/workspace/nanoclaw && nohup ./.venv/bin/python clean_swap.py >> real_cron.log 2>&1 &
*/2 * * * * pgrep -f "clean_swap.py" >/dev/null || (cd ~/.nanobot/workspace/nanoclaw && nohup ./.venv/bin/python clean_swap.py >> real_cron.log 2>&1 &)
```

Notes:
- `nanokill` intentionally stops the process; cron may restart it within 2 minutes.
- Keep one writer bot per wallet/private key.

## Exceptional Flow: `.env.example` -> `.env` (use only when explicitly intended)

This is not default stage behavior. Use only when you intentionally reset stage runtime env from template.

1. Backup current runtime env:
   - `cp .env .env.bak.$(date +%Y%m%d_%H%M%S)`

2. Replace runtime env from template:
   - `cp .env.example .env`

3. Immediately restore stage secrets/runtime values in `.env`:
   - `POLYGON_PRIVATE_KEY` (or legacy `PRIVATE_KEY`)
   - RPC values (`RPC`, `RPC_URL`, `WEB3_PROVIDER_URI`)
   - Any stage integrations (`ONEINCH_API_KEY`, `GROK_API_KEY`, `TELEGRAM_*`, etc.)
   - Current required knobs for this cycle:
     - `COOLDOWN_MINUTES=3`
     - `TEST_MODE=true`
     - `COPY_RATIO=0.20`
     - `MIN_TRADE_USD=15`
     - `MIN_TRADE_USDC=15`
     - `HARD_BYPASS_ENABLED=true`

4. Validate consistency:
   - `python scripts/verify_env_example_keys.py`

5. Restart and verify:
   - `nanokill && nanoup`
   - `nanostatus && nanopnl && ./nanodaily`

## Guardrails

- Do not paste secrets in chat or commit `.env`.
- Do not run two write-enabled bot instances for the same wallet.
- Prefer `nanoup`/`nanorestart` over ad-hoc pull/restart commands.
- If deploy looks wrong, restore env quickly:
  - `cp .env.bak.<timestamp> .env`
  - `nanokill && nanoup`

## Related Docs

- `AI_CONTEXT.md`
- `docs/OPERATING_MODEL.md`
- `docs/DEV_WORKFLOW.md`
- `scripts/nanoup.sh`
- `scripts/nanoenv_example.py`
- `scripts/verify_env_example_keys.py`
