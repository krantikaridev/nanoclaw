# Operating Model (Human + Grok + Cursor)

This page defines who does what so execution is repeatable and role confusion stays low.

## Roles

- **Grok (strategy/review partner)**
  - Helps set vision, priorities, and acceptance criteria.
  - Reviews outcomes and helps decide next deltas.
  - Produces clear implementation prompts for Cursor when requested by human.

- **Human operator (owner/approver)**
  - Decides priorities, risk posture, and when to deploy.
  - Runs/approves VM-stage commands, validates runtime behavior, and confirms readiness.
  - Reviews Cursor changes before push/deploy.

- **Cursor (implementation engine)**
  - Implements major functionality and refactors.
  - Adds/updates tests and docs with code changes.
  - Produces repo-ready diffs for human review and push.

## Standard Loop

1. **Brainstorm and prioritize** (Grok + Human).
2. **Create execution prompt** (Grok -> Human -> Cursor).
3. **Implement in local repo** (Cursor), with tests/docs/env-template alignment.
4. **Human review + push from local**.
5. **Deploy on VM/stage** (Human) using the VM runbook.
6. **Observe logs/PnL and validate** (Grok + Human).
7. **Tune env or apply small follow-up fixes** as needed.
8. Repeat.

## Deployment Responsibility Split

- **Major functionality**: done in Cursor/local, reviewed, then pushed.
- **Runtime tuning and incident response**: usually small VM-stage changes (env, restart, health checks), then fed back into repo as needed.

## Rules Everyone Follows

- Keep `.env` as runtime truth; never commit it.
- Keep `.env.example` in sync using:
  - `python scripts/nanoenv_example.py --write`
  - `python scripts/verify_env_example_keys.py`
- Use repo command layer (`nanoup`, `nanokill`, `nanorestart`, `nanostatus`) via:
  - `scripts/nanobot_aliases.sh --install`
- Never run two write-enabled bots on the same wallet key.
- Verify on VM before declaring done (`git log`, runtime logs, `nanopnl`/`nanostatus`).

## Canonical References

- Global context/backlog/rules: `AI_CONTEXT.md`
- VM deployment flow: `docs/readme-vm-update.md`
- Commit/test/env workflow: `docs/DEV_WORKFLOW.md`
