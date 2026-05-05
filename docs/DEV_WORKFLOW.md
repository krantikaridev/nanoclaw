# Nanoclaw Development Workflow Constitution

This file is the operational source of truth for day-to-day work.

Role boundaries and collaboration are defined in `docs/OPERATING_MODEL.md`.

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
  - health/log checks (`nanostatus`, `nanopnl`, `nanobot`, `nanodaily`)
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
  - AUTO-USDC prep may run even when per-asset cooldown is not ready if a high-conviction BUY signal is active; this is intentional to pre-fund USDC for the next eligible BUY path.
- Before commit:
  1. `python -m ruff check .`
  2. `python -m compileall -q .`
  3. `python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml`
  4. `git diff --stat` and verify only intended files.
- Any behavior/config change must include tests + docs + `.env.example` updates in same PR.

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

1. Confirm bot/runtime state (`nanostatus`, `nanopnl`, `tail -n 120 real_cron.log` if needed).
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
