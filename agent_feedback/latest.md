# Latest Feedback (28 Apr 2026)

## What shipped

- USDC copy strategy fully wired into `clean_swap.py` (top-level instantiation + prioritized after protection/profit).
- X-Signal tokenized equity trader added (`SignalEquityTrader`) with dynamic asset list from `followed_equities.json` (no hardcoded 4-stock limit).
- Swap execution now supports token-in/token-out routes for equity swaps (keeps existing direction-based WMATIC/USDC swaps unchanged).
- Token addresses and router/ABI configuration moved to `.env` with JSON ABI files (env-overridable).
- VM tooling scripts added: `scripts/fix_vm.sh` and `scripts/vm_health.sh` (both executable) for fast recovery + diagnostics.
- Hardened ops scripts:
  - `fix_vm.sh`: removed dead zombie-kill, changed to parent-PID cleanup; removed hardcoded `.env.local` gas overrides (now opt-in via env vars).
  - `vm_health.sh`: RPC check now reports OK/FAILED/INCONCLUSIVE with timeout; endpoint overridable via `NANOCLAW_RPC_URL`.
- Safety fix: `USDT` now has a default token address in `constants.py` to avoid `None` crashes when env is missing.

## Known constraints

- Only **one on-chain swap** is executed per cycle (nonce safety). Both strategies can evaluate “in parallel”, but execution is serialized.
- Equity execution requires tokenized equity token addresses to be set via env (e.g., `GOOGLON`, `MSFTON`, `APPLON`, `AMZNON`).

## Next actions

- Keep `real_cron.log` / runtime logs untracked (never commit); rely on `.gitignore` + remove from index if it ever gets tracked.
- Add wallet scoring / quality filtering for copy wallets (reduce noise, increase hit rate).
- Add “dry-run” mode for equity and copy flows (log-only) to validate decisions without broadcasting transactions.
- Consider making `vm_health.sh` prefer `.env.local` `RPC` when present to avoid hardcoded defaults.

