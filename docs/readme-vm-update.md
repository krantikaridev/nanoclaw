# VM Update Runbook (Reusable)

Canonical stage VM deploy flow for branch `V2`. Use this whenever promoting local changes to VM, including release/tag runs.

Role split and decision loop: `docs/OPERATING_MODEL.md`.

## Runtime configuration (single `.env`)

- **Committed template**: `.env.example` (sanitized; no real secrets).
- **VM / local runtime**: `.env` (secrets + values; never commit).
- **`nanoup`** runs `python scripts/nanoenv_apply.py --write`, which merges template into `.env` while **preserving** keys listed in `nanoclaw/env_sync.py` (API keys, `TELEGRAM_CHAT_ID`, and RPC endpoint variables). All other keys reset to whatever is in `.env.example` each deploy.
- To make a tuning knob stick across `nanoup`, **update `.env.example`** (and commit), or extend the preserve list in code (planned review: v2.9—see `AI_CONTEXT.md`).

## Scope

- Repo path: `~/.nanobot/workspace/nanoclaw`
- Branch: `V2`
- Runtime source of truth: `.env`
- Sanitized template in git: `.env.example`

## Explicit checklist: RPC and `MAX_GWEI` on the VM

Follow when logs show placeholder hosts (`YOUR_ACTUAL`, `PASTE_*`), `All RPC endpoints failed`, `fallback_after_all_rpcs_failed`, or `AUTO-USDC skipped — gas/POL guard (gas_ok=False)` while live gas is obviously above `MAX_GWEI`.

### 1) Edit runtime env on the VM only

```bash
cd ~/.nanobot/workspace/nanoclaw
nano .env
```

### 2) Remove placeholder URL text

Anything that is not a reachable HTTPS RPC is wrong: `YOUR_…`, `PASTE_…`, `<…>`, tutorial strings.

Check (should print nothing):

```bash
grep -Ei 'YOUR_ACTUAL|PASTE_REAL|YOUR_RPC|changeme|<paste' .env || echo OK
```

### 3) Set RPC fields (what each line does)

Put **comma-separated HTTPS URLs** in **`RPC_ENDPOINTS`** (no quotes). Order matters: **left = tried first**.

| Variable | Use |
|---------|-----|
| `RPC_ENDPOINTS` | Main ordered list for Polygon JSON-RPC HTTPS endpoints. Include your best URL first, then public fallbacks (e.g. polygon-rpc.com, llamarpc, ankr `/polygon`). |
| `RPC` | Single legacy endpoint. Either match your preferred first URL or leave empty—do **not** leave an invalid URL here. |
| `RPC_URL`, `WEB3_PROVIDER_URI` | Optional aliases other code uses; safest is to align them with the same HTTPS URL as `RPC` or first `RPC_ENDPOINTS` entry. |

**If `RPC=` contains `rpc.ankr.com/multichain/<long-hex>`:** that path usually embeds provider credentials. Keep it **only in VM `.env`**. **Do not copy it into `.env.example`** or run `nanoenv_example.py --write` until sanitized; rotate at Ankr if it leaked.

### 4) Raise `MAX_GWEI` when gas blocks swaps / AUTO‑USDC

Find `MAX_GWEI=` in `.env`. If logs show ~130 **gwei** and `MAX_GWEI=80`, set e.g. **`MAX_GWEI=150`** so `gas_ok` can pass during congestion.

Durability:

- **`nanoup` merges template → `.env` but preserves RPC keys—not `MAX_GWEI`** (see `ENV_APPLY_PRESERVE_KEYS` in `nanoclaw/env_sync.py`).
- After you pick a ceiling, bump the same **`MAX_GWEI=`** in repo **`.env.example`**, commit, push, VM `pull`, then **`NANOUP_AUTOSTASH=1 nanoup`** so redeploy does not silently reset gas limits.

### 5) Connectivity probe (handles `RPC_ENDPOINTS` as a list in `config`)

```bash
python - <<'PY'
from web3 import Web3
import config as c
eps = list(c.RPC_ENDPOINTS or [])
url = eps[0] if eps else (c.RPC or c.RPC_URL or c.WEB3_PROVIDER_URI or "").strip()
if not url:
    raise SystemExit("No RPC configured; set RPC_ENDPOINTS or RPC in .env")
print("Using:", url)
w3 = Web3(Web3.HTTPProvider(url))
ok = w3.is_connected()
print("connected:", ok, "chain_id:", w3.eth.chain_id if ok else None)
PY
```

Expect **`connected: True`** and **`chain_id: 137`** (Polygon PoS).

### 6) Restart and spot-check RPC lines in the log

```bash
NANOUP_AUTOSTASH=1 nanoup
grep -E "Trying RPC endpoint|RPC .* failed|All RPC endpoints failed|WALLET TOTAL USD|AUTO-USDC skipped" real_cron.log | tail -n 50
```

### 7) Time-bounded monitoring grep

Do **not** try to reconstruct the MONITOR stamp with `date --date`; use a unique marker:

```bash
MARK="=== MONITOR_$(date +%s) ==="
echo "$MARK" >> real_cron.log
sleep 180
grep -A400 "$MARK" real_cron.log | tail -n 120
```

## `nanoenv_example.py` — credential warning before `git push`

`python scripts/nanoenv_example.py --write` copies **sanitized** values from `.env` into `.env.example` for parity. That is **never** permission to leak **paid RPC URLs** (Ankr `/multichain/…`), private keys, or API secrets.

Before commit:

```bash
git diff .env.example
```

If **`RPC=`** gained a keyed URL, **`git checkout -- .env.example`**, scrub `.env` first, redo sync manually for public URLs only.

## Optional: deposit USDC (no trading-bot automation required)

Plain-language: send **USDC on Polygon** to the bot **`WALLET=`** address. Step-by-step: **`docs/OPERATOR_SEND_USDC_POLYGON.md`**.

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
`scripts/pnl_report.py` prefers live balance snapshots (paired `WALLET BALANCE` + `Real USDT` and direct `Real USDT`), chooses the most recent usable live snapshot, and only falls back to `MANUAL CORRECT BALANCE` when live data is not usable. Live/manual snapshots are filtered by sanity checks (finite, non-negative, and reasonable component bounds) before source preference is applied.

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
     - `.env` sync from `.env.example` via `scripts/nanoenv_apply.py --write` (preserves secrets + runtime RPC keys)

3. VM env parity sync (required before push/tag from VM):
   - **`python scripts/nanoenv_example.py --write`** — then **`git diff .env.example`** and confirm **no keyed RPC URLs** (e.g. Ankr `/multichain/…`), no real API keys, match public template policy. If in doubt: **`git checkout -- .env.example`** and hand-edit public defaults only.
   - `python scripts/verify_env_example_keys.py`
   - `git push` also enforces parity via pre-push hook; one-time override:
     - `NANOCLAW_CONFIRM_ENV_SYNC_SKIP=1 git push`

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

2. Replace runtime env from template while preserving secrets:
   - `python scripts/nanoenv_apply.py --write`
   - Default preserve set also keeps runtime RPC keys: `RPC_ENDPOINTS`, `RPC`, `RPC_URL`, `WEB3_PROVIDER_URI`, `RPC_FALLBACKS`.

3. Immediately verify preserved runtime values in `.env`:
   - `POLYGON_PRIVATE_KEY` (or legacy `PRIVATE_KEY`)
   - Any stage integrations (`ONEINCH_API_KEY`, `GROK_API_KEY`, `TELEGRAM_*`, etc.)
   - RPC chain (`RPC_ENDPOINTS` preferred) with real URLs only (no placeholders)
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
- `portfolio_session_baseline.json` is runtime-only and ignored by git; do not stage/commit it.
- If deploy looks wrong, restore env quickly:
  - `cp .env.bak.<timestamp> .env`
  - `nanokill && nanoup`

## Related Docs

- **`docs/OPERATOR_SEND_USDC_POLYGON.md`** (beginner: send USDC on Polygon to **`WALLET`**)
- `AI_CONTEXT.md`
- `docs/OPERATING_MODEL.md`
- `docs/DEV_WORKFLOW.md`
- `scripts/nanoup.sh`
- `scripts/nanoenv_example.py`
- `scripts/verify_env_example_keys.py`
