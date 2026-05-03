# Environment: RPC precedence and health checks

This is the **intended** behavior in the repo today; adjust in `nanoclaw.config` / `nanoclaw.utils.gas_protector` if operations need a different policy.

## Primary URL (on-chain reads, swaps, `connect_web3`)

`nanoclaw.config.default_json_rpc_url()` builds an **ordered list**:

1. **First non-empty** among, in order: `RPC` → `RPC_URL` → `WEB3_PROVIDER_URI` (each trimmed). That value is the **primary** endpoint.
2. After the primary, the list appends the built-in public Polygon URLs **in fixed order** (`_DEFAULT_POLYGON_PUBLIC_RPCS` in `nanoclaw/config.py`), **skipping duplicates** already in the list.

`connect_web3()` without arguments walks that list: for each URL it builds `Web3.HTTPProvider`, calls `eth.block_number`, and returns the first client that succeeds (with a few transient retries per URL). If all fail, it raises.

**Operator guidance:** Set **`RPC` and `RPC_URL` to the same URL** (your paid or preferred node). Use `WEB3_PROVIDER_URI` only as a **legacy alias** for tools that do not know `RPC`; if you set `RPC` / `RPC_URL`, `WEB3_PROVIDER_URI` is **not** used as primary. Avoid pointing `RPC` at host A and `WEB3_PROVIDER_URI` at host B unless you are debugging—mixed primaries have caused confusing behavior in the field.

## `RPC_FALLBACKS` (gas / POL checks only)

`GasProtectorBuilder` in `nanoclaw/utils/gas_protector.py` does **not** replace the list above. It:

- Takes the same default chain from `default_json_rpc_url()`.
- Sets **primary** to the first URL and **fallbacks** to the **rest of that chain** plus any extra URLs from **`RPC_FALLBACKS`** (comma-separated, trimmed).

So **`RPC_FALLBACKS` may be left empty**; you still get all public fallbacks after the primary. Use `RPC_FALLBACKS` for **extra** endpoints (e.g. a backup Ankr key, a private node) that you want the gas/POL probe to try in addition to the default chain.

## ROI / PnL baseline (separate from RPC)

Portfolio return labels use `modules/baseline.py`, not the RPC list. **`PORTFOLIO_BASELINE_USD=0`** (or unset/empty) means “do not pin from env”—baseline resolves from `portfolio_baseline.json`, then the first `portfolio_history.csv` row, then the caller’s live total. Any **positive** value pins starting capital for ROI-style labels.
