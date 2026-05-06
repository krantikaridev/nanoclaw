# External layer

<!-- This folder contains the new External Risk + Agent Layer: JSON control surface (`control.json`), helpers in `control.py`, and risk hooks in `risk_checker.py`. -->

## Operator loop

Run `python external_layer/control.py` from the repo root to overwrite **`control.json` about every 25 seconds** (20–30s) with the latest risk evaluation: live Polygon **USDT** and **WMATIC** balances, `paused` / optional `reason` (low-balance protection), plus defaults nanoclaw already reads. Uses the same RPC resolution as the bot (`RPC` / `RPC_ENDPOINTS` / `connect_web3` fallbacks). If a balance read fails, the process keeps the last good pause state and logs a warning. Stop with Ctrl+C.
