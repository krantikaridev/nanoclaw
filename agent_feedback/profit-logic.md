# Task Log: Profit Logic

## Outcome

- Profit-taking logic supports:
  - \(8\%\) take-profit with configurable sell fraction
  - \(12\%\) strong signal take-profit with configurable sell fraction
  - \(5\%\) trailing stop after TP is reached (pullback from peak)
- Added stateful tracking (`profit_tracking`) that resets safely when no open trade exists.

## Why it matters

- Locks profit more consistently without requiring full exits.
- Reduces “round-trip” losses by respecting peak pullbacks.

## Follow-ups

- Add a minimum holding time filter to avoid immediate churn after buys.
- Add per-trade metadata so we can evaluate which triggers work best.

