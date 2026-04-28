# Latest Feedback (28 Apr 2026)

## What shipped

- USDC copy strategy added (builder-based + gas-protected) and integrated to run alongside WMATIC evaluation.
- Token addresses and router/ABI configuration moved to `.env` with JSON ABI files (env-overridable).

## Known constraints

- Only **one on-chain swap** is executed per cycle (nonce safety). Both strategies can evaluate “in parallel”, but execution is serialized.

## Next actions

- Add wallet scoring / quality filtering for copy wallets (reduce noise, increase hit rate).
- Add “dry-run” mode for swaps (log-only) to validate strategy decisions without broadcasting transactions.

