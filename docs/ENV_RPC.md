# Environment: RPC precedence and health checks

This is the **intended** behavior in the repo today; adjust in `nanoclaw.config` / `nanoclaw.utils.gas_protector` if operations need a different policy.

## Primary URL (on-chain reads, swaps, `connect_web3`)

`nanoclaw.config.default_json_rpc_url()` builds an **ordered list**:

1. `RPC_ENDPOINTS` entries first (comma-separated, trimmed, in order).
2. Then `RPC_FALLBACKS` entries (if any), preserving order.
3. Then the first non-empty among `RPC` → `RPC_URL` → `WEB3_PROVIDER_URI` if not already included.
4. After env entries, built-in public Polygon URLs in fixed order (`_DEFAULT_POLYGON_PUBLIC_RPCS` in `nanoclaw/config.py`), skipping duplicates.

`connect_web3()` without arguments walks that list: for each URL it builds `Web3.HTTPProvider`, calls `eth.block_number`, and returns the first client that succeeds (with a few transient retries per URL). If all fail, it raises.

**Operator guidance:** Prefer **`RPC_ENDPOINTS`** with 2–3 HTTPS providers in priority order, and keep `RPC` / `RPC_URL` / `WEB3_PROVIDER_URI` aligned with your primary where tools still read those aliases.

Always use real reachable URLs in runtime `.env`; remove tutorial placeholders (`YOUR_*`, `PASTE_*`). In Python, **`config.RPC_ENDPOINTS` is a `list`**, not a string—use the probe in **`docs/readme-vm-update.md`** (section *Explicit checklist: RPC and `MAX_GWEI`*) instead of calling `.strip()` on it.

Example:

`RPC_ENDPOINTS=https://polygon-rpc.com,https://rpc.ankr.com/polygon,https://polygon.llamarpc.com`

## `RPC_FALLBACKS` (optional extras)

`GasProtectorBuilder` in `nanoclaw/utils/gas_protector.py` does **not** replace the list above. It:

- Takes the same default chain from `default_json_rpc_url()`.
- Sets **primary** to the first URL and **fallbacks** to the **rest of that chain** plus any extra URLs from **`RPC_FALLBACKS`** (comma-separated, trimmed).

So **`RPC_FALLBACKS` may be left empty**; you still get all public fallbacks after the primary. Use `RPC_FALLBACKS` for **extra** endpoints (e.g. a backup Ankr key, a private node) that you want the gas/POL probe to try in addition to the default chain.

## ROI / PnL baseline (separate from RPC)

Portfolio return labels use `modules/baseline.py`, not the RPC list. **`PORTFOLIO_BASELINE_USD=0`** (or unset/empty) means “do not pin from env”—baseline resolves from `portfolio_baseline.json`, then the first `portfolio_history.csv` row, then the caller’s live total. Any **positive** value pins starting capital for ROI-style labels.
