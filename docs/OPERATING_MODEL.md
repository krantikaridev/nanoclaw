# Operating Model (Human + Grok + Cursor)

This file only defines roles and collaboration.  
Execution rules live in `docs/DEV_WORKFLOW.md`.

## Roles

- **Human (krantikari)**
  - Owns priorities, risk posture, and final go/no-go decisions.
  - Approves deploys and confirms runtime behavior on VM.
  - Decides when a task is complete.

- **Grok (strategy + review partner)**
  - Helps shape strategy, acceptance criteria, and task breakdown.
  - Challenges weak assumptions and raises risk/regression concerns.
  - Produces clear prompts/checklists for implementation when needed.

- **Cursor (implementation engine)**
  - Implements code changes in local repo.
  - Updates tests/docs with behavior changes.
  - Delivers review-ready, verifiable diffs.

## Collaboration Loop

1. Human + Grok align on target outcome and acceptance checklist.
2. Cursor implements in one cohesive pass (code + tests + docs).
3. Human reviews diff and test evidence.
4. Human deploys to VM using workflow scripts.
5. Human + Grok review runtime signals/PnL and define next iteration.

## Handoff Contract

Every handoff between Human, Grok, and Cursor includes:

- current objective
- current state (what is done / not done)
- exact next action
- blockers or risks

No handoff is complete without these 4 items.

## Non-Negotiables

- One writer bot per wallet/private key.
- No secret sharing in chat or commits.
- No “done” without verification evidence.
- Workflow/process truth lives in `docs/DEV_WORKFLOW.md`.
