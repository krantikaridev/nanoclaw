Run from repo root: `python external_layer/control.py` (polls Polygon balances and refreshes repo-root `control.json` about every 25s).

Nanoclaw loads `control.json` each bot cycle (`load_cycle_control` → `determine_trade_decision`) and uses `paused`, `max_copy_trade_pct`, and `reason` for copy-trade sizing and entry gating.
