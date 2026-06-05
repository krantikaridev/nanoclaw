# Nanoclaw Development Workflow Constitution

This file is the operational source of truth for day-to-day work.

Role boundaries and collaboration are defined in `docs/OPERATING_MODEL.md`.

## Shell: Windows (local) vs Linux (VM)

- **Local**: Developers often use **Windows PowerShell**. Chaining commands with **`&&`** only works on **PowerShell 7+**; on Windows PowerShell 5.x use **`;`** and check **`$LASTEXITCODE`** (see **Release safety gates** in `AI_CONTEXT.md`). Prefer **`scripts/pre_commit_gate.ps1`** for a known-good sequence.
- **Stage VM** (Ubuntu): **`bash`**, `nanoup`, and **`docs/readme-vm-update.md`** examples assume POSIX shell.

When writing agent instructions or runbook steps, **label the shell** if a snippet is not portable.

## Core Principles

- Prefer one-shot flows over multi-step manual sequences.
- If a task needs more than 2-3 manual steps repeatedly, script it.
- Use Cursor for all logic/code changes. Do not use `sed`/`nano`/one-liner hacks for logic edits.
- Use terminal for run/restart/log checks and quick environment fixes only.
- Keep git clean. Runtime artifacts must never be committed.

## Single Source Of Truth

- Workflow and guardrails: `docs/DEV_WORKFLOW.md` (this file).
- Active execution backlog: `TODO.md`.
- Session context and continuity notes: `AI_CONTEXT.md`.
- Every session starts by reading these before touching code.

## Session Start Checklist (first 2 minutes)

1. Read `docs/DEV_WORKFLOW.md`, `TODO.md`, and `AI_CONTEXT.md`.
2. Confirm branch and working tree:
   - `git branch --show-current`
   - `git status --short`
3. Verify no surprise runtime file staging (`portfolio_history.csv`, `real_cron.log`).
4. Confirm current task acceptance criteria in one short checklist.

## Cursor vs Terminal Rule

- **Cursor only**:
  - strategy logic
  - refactors
  - tests
  - docs updates tied to behavior changes
- **Terminal only**:
  - run/test commands
  - restart/stop bot (`nanoup`, `nanokill`, `nanorestart`)
  - health/log checks (`nanohealth`, `nanostatus`, `nanopnl`, `nanobot`, `nanodaily`)
  - emergency env/runtime fixes
- Never patch Python business logic through terminal editors.

## Git Rules (strict)

- Do not use rebase/pull conflict gymnastics for normal deploy flow.
- Never stage runtime artifacts (`portfolio_history.csv`, `real_cron.log`).
- Keep hooks enabled: `git config core.hooksPath .githooks`.
- Push gate on VM:
  - `.githooks/pre-push` blocks push when `.env.example` drifts from sanitized `.env`.
  - Sync with: `python scripts/nanoenv_example.py --write && python scripts/verify_env_example_keys.py`.
  - One-push override (explicit operator confirmation): `NANOCLAW_CONFIRM_ENV_SYNC_SKIP=1 git push`.
- Strategy precedence note:
  - Dust-sized protection exits (`< MIN_TRADE_USD`) are non-blocking; cycle falls through to the next strategy in precedence.
  - Same non-blocking dust defer applies to downstream branches (`PROFIT_TAKE`, `X_SIGNAL_EQUITY`, `USDC_COPY`/`POLYCOPY`, `MAIN_STRATEGY`) to prevent single-branch dust loops from monopolizing cycles.
  - `MIN_TRADE_USD` remains a global hard execution floor; dust defer only affects branch fallthrough, never execution safety.
  - **TEMPORARY SPRINT FIX (May 2026)**: `PROFIT_TAKE` / `MAIN_STRATEGY` may run small WMATIC→USDT/USDC notionals (≥ **$8.00** P2 floor and below `MIN_TRADE_USD`) when total WMATIC USD equivalent and signal strength pass tiered gates (`modules/swap_executor._wmatic_stable_p2_relief_override_active` calls `_profit_take_balance_relief_bypass_allowed` first, before dust defer). Logs: `[nanoclaw] P2 relief check`, `[nanoclaw] P2 RELIEF OVERRIDE ACTIVE | WMATIC=… | notional=… | bypassing min_notional`, `[nanoclaw] Main strategy small profit take allowed (P2 relief)`, `[nanoclaw] FORCE small profit take | WMATIC healthy, forcing exit` (tiered idle cycles; WMATIC ≥ tier wm floor).
  - **TEMPORARY**: small high-conviction X-SIGNAL (`USDC_TO_EQUITY`, `abs(signal) ≥ 0.85`, notional ≤ ~$12) may use very high fallback-router slippage (`X_SIGNAL_SMALL_HIGH_CONVICTION_FALLBACK_*_BPS`, default 8000/10000 bps); look for `[nanoclaw-av] X-SIGNAL using very high slippage for small trade (high conviction)`.
  - AUTO-USDC prep may run even when per-asset cooldown is not ready if a high-conviction BUY signal is active; this is intentional to pre-fund USDC for the next eligible BUY path.
  - Per-trade protection evaluates the latest valid `OPEN` lock entry only (instead of every historical `OPEN`) to prevent stale lock rows from repeatedly forcing precedence.
- Before commit:
  1. `python -m ruff check .`
  2. `python -m compileall -q .`
  3. `python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml`
  4. `git diff --stat` and verify only intended files.
- Any behavior/config change must include tests + docs + `.env.example` updates in same PR.

## V4-play lab branch (parallel to stage)

**Stage wallet stays on `V2`** (tag `v2-stage-2026-06-05` @ `738222ed`) while paused. **`V4-play`** is for a **second VM + new wallet** only.

| Step | Where | Action |
|------|--------|--------|
| 1 | Dev | `git checkout V4-play && git pull` |
| 2 | Lab VM | Fund **$60–100** USDC + POL; new `WALLET=` in `.env` |
| 3 | Lab VM | `bash scripts/v3_pre_deploy_check.sh` → `NANOUP_AUTOSTASH=1 nanodeploy` |
| 4 | Lab VM | Run **48h**; see [`docs/ROTATION_PLAYBOOK.md`](ROTATION_PLAYBOOK.md) |
| 5 | Dev | Merge `V4-play` → `V2` only after lab gate + operator sign-off |

Sprint prompts: [`docs/AGENT_SPRINT_PROMPTS_V4.md`](AGENT_SPRINT_PROMPTS_V4.md).

## V3 merge gate

V3 is **dev/CI only** until the parent merges to `V2` and deploys. The live stage VM stays on **`V2`** while monitoring (auto-pause, 12h window PnL, post-derisk book).

| Step | Where | Action |
|------|--------|--------|
| 1 | Dev machine | `git checkout V3 && git pull` |
| 2 | Dev machine | `bash scripts/v3_pre_deploy_check.sh` — **must exit 0** |
| 3 | Stage VM (still on V2) | `nano12h` window **PASS**, `paused=False` stable ≥4h **or** operator accepts risk |
| 4 | Dev machine | Merge `V3` → `V2`, push |
| 5 | Stage VM | `NANOUP_AUTOSTASH=1 nanodeploy` |
| 6 | Stage VM | Post-deploy verify (see below) |

**Do not `nanodeploy` V3 directly** to stage while V2 is live-monitoring.

### What `v3_pre_deploy_check.sh` runs

One command before merge/deploy. Fails fast (non-zero exit) on any step:

1. **Checklist** — prints `git log -1 --oneline`; verifies V3 sprint env keys exist in `.env.example`
2. **`verify_env_example_keys.py`** — config/template coverage
3. **`python -m compileall`** — `nanoclaw`, `modules`, `scripts`, `external_layer`
4. **`python scripts/unpause_readiness.py`** — hard unpause gates (loss-cut off, FE runway, blocklist)
5. **Targeted pytest** — wave 1–3 sprint modules + attribution/env_sync
6. **`TIERED allow` regression** — `test_runway_lines_scoped_to_window_with_timestamps` (stale pre-deploy `TIERED allow` must not appear in 12h runway tail)
7. **Dry `nano_green` runway** — fixture log at `tests/fixtures/v3_pre_deploy/real_cron.log` (same assertion, no RPC)

Windows (Git Bash or WSL): run the same `bash scripts/v3_pre_deploy_check.sh`. For day-to-day commits on Windows PowerShell, use `scripts/pre_commit_gate.ps1` instead.

### Post-merge verification (stage VM)

After `nanodeploy` on `V2`:

```bash
git log -1 --oneline
grep DERISK real_cron.log | tail -n 5
nano12h | grep -E 'window|control|fe_share|runway'
```

Confirm: no ping-pong `FE STABLE RUNWAY TIERED | allow` at stables **< $23**; window gate stable.

### References

- Sprint agent prompts and parent pytest list: [`docs/AGENT_SPRINT_PROMPTS_V3.md`](AGENT_SPRINT_PROMPTS_V3.md)
- Branch fork baseline: `V2` ≥ `02c5fcd7`

## Stable Trading Validation (Pre-Tag)

Run this checklist before creating a release tag (for `v2.7` and later):

1. Keep one bot process running (watchdog cron only) for a continuous 30-60 minute window.
2. Confirm no lock thrash:
   - No repeated lock-active spam loops.
   - No overlapping writer processes for `clean_swap.py`.
3. Confirm non-blocking dust behavior:
   - Logs may show `* DUST DEFER`, but cycle should continue to downstream paths in the same loop.
   - No single branch repeatedly owning cycles with sub-min notional exits.
4. Confirm at least one actionable path exists under current market state:
   - Either a non-dust strategy decision appears, or AUTO-USDC top-up runs under valid BUY conditions.
5. Then run commit gate:
   - `python -m ruff check .`
   - `python -m compileall -q .`
   - `python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml`
6. Data-quality cross-check (required before interpreting PnL):
   - Compare `nanodaily`/`nanostatus` total against wallet-truth runtime telemetry (`WALLET TOTAL USD`) and wallet/on-chain view.
   - Treat `WALLET TOTAL USD` as authoritative; legacy `Real USDT` parser values are fallback only.
   - If totals diverge, treat reported PnL as provisional and log a parser/source reconciliation task before tagging.

Fast iteration mode (for stage diagnosis loops, not final sign-off):
- Add marker: `echo "=== FAST_WINDOW_START $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> real_cron.log`
- Poll up to ~6 minutes (30s slices) and break on first success signal (`REAL TX HASH` / `Swap executed successfully`).
- Summarize with:
  - `grep -A9999 "FAST_WINDOW_START" real_cron.log | grep -E "Swap executed successfully|REAL TX HASH|DECISION PATH|DUST DEFER|min_trade_guard|Lock active" | tail -n 200`
- Keep final pre-tag decision on a longer window (30-60 minutes) even when fast mode is green.

Runtime/template note:

- **`nanoup`** merges `.env.example` → `.env` (`scripts/nanoenv_apply.py`), preserving secrets and RPC-related keys only. Promote tuning by updating `.env.example` (sanitized), then VM `pull`/`nanoup`.
- Edits to `.env` alone may be overwritten on the next `nanoup` unless those keys are in `.env.example` afterward or on the preserve list—see `nanoclaw/env_sync.py`.
- `.env.example` must remain sanitized and document knobs/semantics (not secret values or machine-specific endpoints).

Windows gate shortcut:
- `powershell -ExecutionPolicy Bypass -File .\scripts\pre_commit_gate.ps1`
- or `.\scripts\pre_commit_gate.cmd`

## VM + Cursor Sync Rules

- Develop logic locally in Cursor, then push to branch.
- On VM, use script-driven flow (`nanoup` / `nanorestart`), not ad-hoc pull/restart chains.
- `nanostatus`, `nanopnl`, and `nanorestart` forward CLI args to `scripts/pnl_report.py` (use `--reset-session` when resetting session PnL anchor).
- For dirty VM runtime state, use `NANOUP_AUTOSTASH=1 nanoup` instead of manual stash gymnastics.
- Keep VM runtime and repo template aligned:
  - `python scripts/nanoenv_example.py --write`
  - `python scripts/verify_env_example_keys.py`

## Context Preservation and Handoff

- Every stop (especially late night) must leave:
  - what was changed
  - what is running
  - next exact action
  - blockers/risks
- Record these in `AI_CONTEXT.md` and `TODO.md`.
- Never end a session with unstated assumptions.

## Session End Checklist

1. Confirm bot/runtime state (`nanohealth`, `nanostatus`, `nanopnl`, `tail -n 120 real_cron.log` if needed).
2. Run commit gate for code changes.
3. Ensure runtime artifacts are unstaged.
4. Update `TODO.md` and `AI_CONTEXT.md` with clear next step.
5. Leave working tree intentional (clean, or explicit WIP with reason).

## Automation Rule

- Repeated sequence (more than 2-3 steps) must be converted into:
  - repo script in `scripts/`, or
  - `nano*` command alias/shim.
- Prefer automating safe defaults over relying on memory.

## References

- VM runbook: `docs/readme-vm-update.md`
- RPC/env policy: `docs/ENV_RPC.md`
- Repo hardening checklist: `docs/REPO_HARDENING.md`
