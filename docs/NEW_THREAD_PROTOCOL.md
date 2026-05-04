# New Thread Protocol (Nanoclaw / Grok / Cursor Agents)

Use this checklist when starting a **new Grok conversation**, a fresh **Cursor Chat**, or handing work to another operator so nothing material is lost.

## Why this exists

Trading bots produce **dense state**: env flags, CSV history, staged vs production wallets, incidents (dummy peaks, guard blocks), and backlog items spread across chats. Threads hit message limits—**truth must live in the repo**, anchored by `AI_CONTEXT.md`.

## Before you archive the old thread

1. Note **branch** (`V2`), **environment** (VM path, systemd vs cron, `.env.local` quirks).
2. Note **whether the bot is running** (`nanostatus` sanity, last deploy command).
3. Copy any **URLs** still needed (Polygonscan txs, gist of errors)—do not paste secrets.

## Opening the new thread (first message template)

Paste or adapt blocks in this order (trim only if token budget forces it):

1. **Link**: `AI_CONTEXT.md` raw for `V2`  
   https://raw.githubusercontent.com/krantikaridev/nanoclaw/V2/AI_CONTEXT.md  
   Or paste the **Systematic Learning & History**, **New Thread Protocol**, **House-Cleaning Checklist**, **V2.5.11+ Roadmap**, **TODO & Backlog**, and **Current Situation / Status** sections from your local checkout (they must match repo after edits).

2. **One-line mission**: Example: “Continue nanoclaw `V2` stage bot iteration; no broad refactors; ROI-first deltas only.”

3. **Operational facts**: Public wallet (`WALLET`), current hypothesis, blockers copied from logs (redact RPC URLs if sensitive).

4. **Explicit exclusions**: Example: “Do not paste or request private keys.”

## Seamless continuity rules

| Rule | Detail |
|------|--------|
| **Single source of truth** | Prefer updating `AI_CONTEXT.md` over long chat memory. |
| **Acceptance checklist first** | For non-trivial code, mirror *One-go execution protocol* inside `AI_CONTEXT.md`. |
| **Verify telemetry** | Reconcile totals with Polygonscan—not CSV headlines alone—after incidents. |
| **Branch discipline** | All PRs/target branch agreed in message one (`V2` unless operator says otherwise). |
| **Test gate** | `python -m compileall -q .` and `python -m pytest -q` before declaring done when code changed. |

## After the assistant responds

1. Ask it to **read `/.env.example`**, not `.env`, for keys.
2. Point it at **`clean_swap.py` precedence comments** before strategy edits.
3. If touching history data, mention **`scripts/clean_dummy_data.sh`** and Polygon confirmation.

## Windows vs Linux runners

Operators on Windows use PowerShell gates from `AI_CONTEXT.md`. **VM/deploy** workflows assume Bash—use `./scripts/deploy_vm_safe.sh V2` and shell helpers there.

---

**Reminder**: Repo home — https://github.com/krantikaridev/nanoclaw — branch **`V2`**.
