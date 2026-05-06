
# v3.0 Roadmap: Hybrid Agent System + Positive PnL

**Goal**: Move from slow iterative patching to a **Hybrid Architecture** while achieving consistent positive Session PnL as fast as possible.

**Target Timeline**: 4–5 weeks for a production-ready version with positive expectancy.

**Core Principles**
- Speed through **heavy reuse** of existing open-source work
- GitHub + single `ROADMAP.md` as the source of truth
- Keep `nanoclaw` as the Execution Layer (for now)
- Build intelligence in an **External Agent + Risk Layer**
- Run multiple plays in parallel under one controlled system
- Stay agile and ready to pivot

---

## Current Status (as of 6 May 2026)

- Session PnL: **-3.39%** and still worsening
- Bot put into **Maximum Defensive Mode** (reduced aggression + tighter protection)
- Risk detection is working well, but defensive response is still not strong enough

---

## Phases

### Phase 0: Maximum Defensive Mode (Current)
**Status**: In progress

**Tasks**
- Keep bot in defensive mode
- Monitor Session PnL and protection frequency for 24–48 hours
- Decide whether to further reduce exposure or pause new entries

**Cursor Prompt (when needed)**:
> Review current defensive settings and recent protection triggers. Suggest any additional short-term changes to further reduce risk.

---

### Phase 1: Design External Agent + Risk Layer (Next Priority)

**Goal**: Move risk decisions and strategy control **outside** the core trading bot so we can iterate much faster.

**Key Requirements**
- External layer should control/pause `nanoclaw`
- Support multiple strategies (current + Polymarket)
- Easy to experiment with (agentic style)

**Focus**
- Heavily leverage patterns from `HKUDS/AI-Trader` and `second-state/fintool`
- Design clean separation between Execution and Intelligence layers

**Cursor Prompt (when starting this phase)**:
> Propose a modular architecture for the External Risk + Agent Layer. Prioritize speed of iteration and reuse of existing patterns from HKUDS/AI-Trader and second-state/fintool.

---

### Phase 2: Codebase Audit & Cleanup

**Goal**: Reduce technical debt and make the codebase more maintainable and modular.

**Tasks**
- Identify legacy and unused code
- Find brittle coupling points
- Propose cleanup priority and modular improvements

**Cursor Prompt**:
> Perform a high-level audit of the current codebase. List the biggest sources of technical debt and recommend a cleanup priority.

---

### Phase 3: Build External Risk + Agent Layer v1

**Goal**: Create the first working version of the external control layer.

**Tasks**
- Implement basic risk assessment outside the bot
- Add ability to pause/resume trading
- Start moving defensive logic out of `signal.py`

---

### Phase 4: Polymarket Side Strategy (Parallel Track)

**Goal**: Add a second strategy using prediction markets for diversification and learning.

**Approach**
- Start small
- Leverage existing Polymarket bot patterns
- Run under the same risk layer

---

## Open Decisions

- Should we eventually replace parts of `nanoclaw` execution, or keep it long-term as the execution engine?
- Preferred agent framework for the External Layer (`OpenClaw`, custom, or adapt from `HKUDS/AI-Trader`)?

---

## How to Work

1. Pick one task from this file
2. Copy the relevant section + Cursor prompt
3. Work on it
4. Update this file with progress
5. Commit changes

This file is the single source of truth.
