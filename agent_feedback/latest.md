# Latest Feedback (28 Apr 2026)

## What shipped

- USDC copy strategy added (builder-based + gas-protected) and integrated to run alongside WMATIC evaluation.
- Token addresses and router/ABI configuration moved to `.env` with JSON ABI files (env-overridable).
- VM tooling scripts added: `scripts/fix_vm.sh` and `scripts/vm_health.sh` (both executable) for fast recovery + diagnostics.
- Hardened ops scripts:
  - `fix_vm.sh`: removed dead zombie-kill, changed to parent-PID cleanup; removed hardcoded `.env.local` gas overrides (now opt-in via env vars).
  - `vm_health.sh`: RPC check now reports OK/FAILED/INCONCLUSIVE with timeout; endpoint overridable via `NANOCLAW_RPC_URL`.
- Safety fix: `USDT` now has a default token address in `constants.py` to avoid `None` crashes when env is missing.

## Known constraints

- Only **one on-chain swap** is executed per cycle (nonce safety). Both strategies can evaluate “in parallel”, but execution is serialized.

## Next actions

- Add wallet scoring / quality filtering for copy wallets (reduce noise, increase hit rate).
- Add “dry-run” mode for swaps (log-only) to validate strategy decisions without broadcasting transactions.
- Consider making `vm_health.sh` prefer `.env.local` `RPC` when present to avoid hardcoded defaults.

