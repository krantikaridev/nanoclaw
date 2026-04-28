# Task Log: Cleanup + Tests

## Outcome

- Archived older/unused folders and stabilized project layout.
- Added unit tests for core decision logic (`clean_swap`) and for `GasProtector`.

## Why it matters

- Faster iteration with less accidental breakage.
- Clearer “source of truth” for strategy behavior.

## Follow-ups

- Ensure tests avoid importing heavy web3 dependencies where possible (keep lightweight fakes).
- Keep test discovery scoped to `tests/` (avoid `archive/` env packages).

