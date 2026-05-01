# Session Feedback - 2026-05-01 Cycle 2 (IST)

## Timestamp

- Date: 2026-05-01
- Time window: evening IST
- Session type: implementation + review-loop retrospection

## Main Prompt (Intent)

- Implement Tier 1 PnL improvements in one go:
  - dynamic position sizing
  - 1inch execution path
  - broaden liquid Polygon assets
- Then run review cycles until clean.
- Finally analyze why too many turns were needed and how to reduce future iterations.

## What Was Completed This Cycle

- Tier 1 implementation delivered:
  - dynamic sizing in `try_x_signal_equity_decision` with requested tiers and comment
  - 1inch swap flow integrated into `swap_executor.py`
  - `followed_equities.json` expanded with USDC + WETH liquid assets
  - per-asset `min_signal_strength` support added and validated in strategy loader/filtering
- Follow-up bug fixes from review:
  - fixed falsy `0.0` floor bug in per-asset threshold logic
  - added router fallback when `ONEINCH_API_KEY` missing or 1inch call fails
  - fixed dynamic size over-allocation risk by capping to available USDC
- Test posture:
  - regression tests added for all above findings
  - compile/test/lint checks passed during cycle

## Why So Many Turns Happened (Root Cause)

1. **Feature-first acceptance criteria, edge-cases discovered later**
   - Initial requirements specified desired behavior, but not complete failure-mode contracts.
   - Missing explicit constraints caused valid first-pass implementation to still have hidden regressions.

2. **Cross-layer coupling increased hidden interaction risk**
   - Changes touched strategy eligibility, sizing, execution transport, config schema, and tests.
   - Cross-layer deltas magnify assumptions that are hard to catch without explicit branch matrix.

3. **Review happened after implementation, not as pre-implementation gate**
   - Issues were caught correctly, but only after code landed and was inspected adversarially.
   - This is healthy, but expensive in turn count.

4. **Ambiguous fallback semantics in integration tasks**
   - "Replace direct router with 1inch" was interpreted as primary path.
   - Missing explicit fallback requirement caused runtime fragility until review correction.

5. **Python truthiness pitfall in config logic**
   - `x or default` for numeric configs silently breaks valid `0.0` values.
   - This is a known class of bug and should be preemptively guarded by checklist/tests.

6. **Post-validation override path bypassed earlier invariant**
   - Dynamic sizing changed final amount after earlier min-floor checks.
   - Final amount boundedness (`<= available_usdc`) was not enforced in the same block initially.

## What Worked Well

- The review loop caught all critical issues before session end.
- Regression tests were added alongside each fix, reducing reintroduction risk.
- The cycle ended in a verified, test-clean state without unsafe git actions.

## Process Gaps To Close

- `AI_CONTEXT.md` is strong for global policy, but it is not a task-contract document.
- A separate task-spec layer is needed to encode:
  - invariants
  - fallback behavior
  - edge-case matrix
  - required tests for touched branches

## Recommended Operating Model (No Repo-Wide Refactor Required Yet)

1. Keep `AI_CONTEXT.md` as global operating context.
2. Add task-level contracts under a dedicated task-spec file per task.
3. Require a pre-code acceptance checklist in chat before edits.
4. Require a "pre-final adversarial pass" against the edge-case matrix.
5. Log lessons into `agent_feedback` each cycle and convert recurring issues into checklist rules.

## Proposed Standard Checklist For Future "One Prompt -> Done" Tasks

- Define scope (allowed files).
- Define invariants (must always hold).
- Define explicit fallback semantics for external dependencies.
- Enumerate edge-case matrix (missing env, zero/falsy values, low balances, external API failures).
- Add at least one regression test per non-happy branch changed.
- Validate with compile + tests + lints before final response.

## Immediate Next Action (Operator)

- Verify current code changes on VM first (runtime sanity and swap behavior).
- Defer process/document restructuring to next iteration (as agreed in this session).

## Closeout Status

- Feedback cycle created.
- Findings and recommendations captured.
- Ready for VM verification handoff.
