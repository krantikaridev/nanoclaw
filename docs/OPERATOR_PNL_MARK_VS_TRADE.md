# Session PnL: mark-to-market vs realized trades

Operators sometimes see **Session PnL** drop with **zero swaps** in the session window. That is often **mark-to-market (MTM)** on followed-equity inventory (`FE_USD`), not a bad fill. This doc explains how to tell the difference and when to reset the session baseline.

**Related:** `AI_CONTEXT.md` (what `TOTAL` / `FE_USD` include), `docs/readme-vm-update.md` (`nanopnl`, `nanodaily`), `.env.example` (`FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY`).

---

## What Session PnL measures

`nanopnl` / `nanodaily` compute:

```
Session PnL = current TOTAL − session_start_total
```

- **`session_start_total`** lives in `portfolio_session_baseline.json` (created on first run or after `nanopnl --reset-session`).
- **`TOTAL`** is the bot’s Polygon-only wallet mark: stables + WMATIC×price + POL×`POL_USD_PRICE` + **`FE_USD`**.

Session PnL is **not** “realized PnL from trades only.” Any component of `TOTAL` can move without a swap:

| Component | Can move without a trade? |
|-----------|---------------------------|
| USDT / USDC | Deposits, withdrawals, gas spend |
| WMATIC / POL | Price marks, unwrap/wrap (logged) |
| **FE_USD** | **Spot cache / live quote / fallback floor** |

Check **velocity** lines in the report (`velocity_fills_session`, turnover) before blaming strategy.

---

## `FE_USD` and `FE_USD AUTO_FLOOR_UPDATE`

**`FE_USD`** is the USDT-notional value of tokens listed in `followed_equities.json` (e.g. Polygon WETH `0x7ceB…`, LINK, WBTC). The runtime quotes each balance via Uniswap paths and applies a **floor** so drained pools do not silently undercount inventory.

**Effective floor per symbol:**

```
effective_floor_px = min(current_price_usd in JSON, last_good_spot from cache)
per-asset USD      = max(live_quote_usdt, balance × effective_floor_px)
```

When a **healthy live quote** confirms value at or above that floor, the bot may persist a new **`last_good_spot_usd`** per symbol in **`.runtime/fe_usd_spot_cache.json`** (gitignored on dev machines; lives on the VM). Upward drift is capped by **`FE_USD_SPOT_CACHE_MAX_UP_PCT_PER_DAY`** (default **5%** / day in `.env.example`).

When the cache spot changes, `real_cron.log` emits:

```
[nanoclaw] FE_USD AUTO_FLOOR_UPDATE | sym=WETH_ALPHA | last_good_spot=2022.0000 | json_floor=2500.0000 | effective_floor=2022.0000
```

**What this means for operators:**

- The bot **re-anchored** the MTM floor to a fresh live spot (here **2022** USD/token), not necessarily a trade loss.
- Stale **`current_price_usd`** in JSON (e.g. **2500**) no longer overstates `TOTAL` when cache or live data is fresher.
- A **downward** cache update (2500 → 2022) lowers **`FE_USD`** and **`TOTAL`** even if **no swap** ran—Session PnL reflects that mark.

**Other FE log lines:**

| Line | Meaning |
|------|---------|
| `FE_USD FALLBACK FLOOR APPLIED` | Live quote below floor; floor won for this cycle |
| `FE_USD UNQUOTED` | No live quote and no usable floor; position may contribute $0 |

Grep on VM:

```bash
grep -E 'FE_USD AUTO_FLOOR_UPDATE|FE_USD FALLBACK|FE_USD UNQUOTED' real_cron.log | tail -30
```

---

## Example: TOTAL $132 → $122 with MetaMask aligned (31 May 2026)

Observed pattern:

- Session PnL **−$10** with **no session fills**.
- MetaMask **Polygon tab** total moved in the same direction as bot **`TOTAL`**.
- Log showed **`FE_USD AUTO_FLOOR_UPDATE | last_good_spot=2022`** (WETH spot cache stepped down from a stale JSON floor).

**Interpretation:** MTM honesty pass on followed equity—not evidence of a silent bad trade. Cross-check Polygon token balances on [Polygonscan](https://polygonscan.com/) for `WALLET=`; quantities should be unchanged if it was mark-only.

`nanopnl` may print a read-only hint when the spot cache moved **>1%** since session start:

```
mark_delta_est: $-10.00 (FE spot cache)
```

That line is an **estimate** from `FE_USD` at session start vs now (log + cache). It does not change trading or baselines.

---

## MetaMask parity — what matches and what does not

The bot is **Polygon PoS only** (chain **137**). **`TOTAL`** is **not** promised to equal MetaMask’s **all-network** headline.

| Compare this | To this |
|--------------|---------|
| MetaMask **Polygon** network selected | Bot `WALLET TOTAL USD` / `nanopnl` **TOTAL** |
| Polygon WETH contract **`0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619`** | `FE_USD` / `followed_equities.json` |
| USDC.e + native USDC + USDT on Polygon | `STABLE_USD` in logs |

**Common mismatches (not bugs):**

- **Ethereum mainnet WETH** (`0xC02a…`) — **out of scope** for v2.8 `TOTAL`; bridge to Polygon or book manually.
- MetaMask **“All popular networks”** — aggregates chains the bot ignores.
- **WMATIC** in logs is **quantity**; USD uses the bot’s live WMATIC price (may differ slightly from MetaMask’s mark).
- **RPC read suspect** warning in `nanopnl` — near-zero stables with large `TOTAL`; fix RPC before trusting PnL (`nanohealth`).

When Session PnL and MetaMask **Polygon tab** move together after `AUTO_FLOOR_UPDATE`, trust the **shared MTM story** over “we must have traded.”

---

## Mark vs trade — quick checklist

1. **`nanohealth`** — RPC green?
2. **`nanopnl`** — read **velocity_fills_session** and **turnover**; zero fills ⇒ no realized swap PnL in window.
3. **`grep FE_USD`** — `AUTO_FLOOR_UPDATE`, `FALLBACK`, `UNQUOTED`?
4. **Polygonscan** — token **balances** unchanged vs **USD** marks moved?
5. **MetaMask** — **Polygon network only**, same contracts as `followed_equities.json`.

If marks explain the delta, **do not** pause trading solely for Session PnL unless risk policy says otherwise.

---

## When to `nanopnl --reset-session` (rare)

Reset **only** when the session baseline no longer matches the story you want to track—not to “hide” MTM moves.

**Good reasons:**

- After a **deploy / config change** where you want PnL from “now” forward.
- After a **deposit or withdrawal** you intentionally exclude from performance view (until v3 flow tagging).
- You previously reset at a bad RPC snapshot and want a clean anchor after **`nanohealth`** is green.

**Usually wrong reasons:**

- Session PnL dropped because **`FE_USD AUTO_FLOOR_UPDATE`** corrected an **overstated** mark (you would erase honest MTM).
- MetaMask all-network total differs from bot Polygon `TOTAL` (reset does not fix scope).
- “Make the number green again” without a structural baseline change.

Command (also via `nanostatus --reset-session` / `nanorestart --reset-session`):

```bash
nanopnl --reset-session
```

This writes current `TOTAL` into `portfolio_session_baseline.json` and sets `session_started_at` to now (UTC).

---

## Commands reference

```bash
nanohealth                    # RPC before trusting PnL
nanopnl                       # full report (+ mark_delta_est when applicable)
nanodaily                     # compact daily summary
grep 'WALLET TOTAL USD' real_cron.log | tail -5
grep 'FE_USD AUTO_FLOOR' real_cron.log | tail -10
cat .runtime/fe_usd_spot_cache.json   # VM only; spot cache per symbol
```
