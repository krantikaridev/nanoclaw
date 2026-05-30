# Copy trading audit — operator backlog (2026-05-30)

> **Status:** Post-freeze backlog item **#4**. Primary live alpha on Instance A is **X-SIGNAL equities** (`followed_equities.json`), not wallet copy. Copy path runs lower in precedence (`USDC copy → polycopy`) and only when `COPY_TRADING_ENABLED=true` and tradeable wallets exist.

---

## Problem (confirmed May 2026)

`followed_wallets.json` on stage listed **Polygon token contract addresses** (USDC, USDT, WMATIC, DAI, etc.), not **EOA trader wallets** to mirror. Logs showed `copy_targets=8` but polycopy never delivered edge — garbage inputs.

**X-SIGNAL is separate:** static `signal_strength` in `followed_equities.json` — not live X/Twitter wallet copy.

---

## One command (run on VM or dev)

```bash
cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate
nanocopyaudit
# or:
python scripts/copy_trading_audit.py
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | OK — copy disabled, or ≥1 tradeable EOA |
| 1 | `COPY_TRADING_ENABLED=true` but no tradeable wallets |
| 2 | All entries are known token contracts (legacy misconfig) |

Runtime safety: when `COPY_TRADING_REJECT_TOKEN_CONTRACTS=true` (default), `get_target_wallets()` **strips** known token contracts before polycopy.

---

## Operator checklist (when re-enabling copy)

1. **Audit current list**
   ```bash
   nanocopyaudit
   cat followed_wallets.json
   grep -E 'copy_targets|COPY TRADE|polycopy|USDC copy' real_cron.log | tail -20
   grep COPY_TRADING .env
   ```

2. **Pick 1–2 trader EOAs** (not token contracts)
   - Verify on [Polygonscan](https://polygonscan.com): **Contract** tab must be absent (EOA).
   - Prefer wallets with: verifiable on-chain history, trade size your gas budget can follow, low overlap with your FE universe (WETH/LINK/WBTC/WMATIC).

3. **Edit `followed_wallets.json`** (use `followed_wallets.json.example` as template)
   ```json
   {
     "wallets": [
       "0xYOUR_VERIFIED_TRADER_EOA_1"
     ],
     "max_copy_ratio": 0.08,
     "notes": "On-chain audit YYYY-MM-DD — Polygonscan + manual review"
   }
   ```

4. **Size conservatively**
   - Start `max_copy_ratio` **0.05–0.08** (5–8% of book per wallet).
   - `control.json` `max_copy_trade_pct` caps copy further (external layer tiers).

5. **Re-run audit until exit 0**
   ```bash
   nanocopyaudit && echo OK
   ```

6. **Optional disable until list is ready**
   ```bash
   grep -q '^COPY_TRADING_ENABLED=false' .env || echo 'COPY_TRADING_ENABLED=false' >> .env
   # survives nanoup if key is in .env (preserved on VM)
   ```

7. **Weekly review** (manual — not automated yet)
   - Polygonscan position diff vs last week
   - `wallet_performance.json` per-wallet PnL
   - Remove wallets with negative rolling edge

---

## What NOT to do

- Do **not** paste USDC/USDT/WMATIC/router addresses into `wallets`.
- Do **not** wire raw X posts or Grok signals straight to copy execution.
- Do **not** enable copy with `control.json paused=false` until FE-heavy BUY guard is shipped (see `docs/GROK_HEAVY_STRATEGY_REVIEW_2026-05-30.md`).

---

## Code map

| File | Role |
|------|------|
| `followed_wallets.json` | Operator wallet list (VM-local edits; repo ships **empty** list) |
| `followed_wallets.json.example` | Schema + comments |
| `copy_trading.py` | Loads list; filters token contracts |
| `modules/copy_trading_audit.py` | Static classification + report |
| `scripts/copy_trading_audit.py` | CLI / `nanocopyaudit` |
| `modules/wallet_performance.py` | Per-wallet PnL after copy fills |
| `modules/swap_executor.py` | Copy precedence + `copy_targets=N` log |
| `.env` | `COPY_TRADING_ENABLED`, `COPY_TRADE_PCT`, `COPY_TRADING_REJECT_TOKEN_CONTRACTS` |

---

## Acceptance (post-freeze side chat)

- [ ] `nanocopyaudit` exit **0** on VM with intentional trader EOAs **or** `COPY_TRADING_ENABLED=false`
- [ ] Log line `copy_targets=N` shows **N = tradeable count**, not 8 token contracts
- [ ] `docs/COPY_TRADING_AUDIT.md` checklist completed in `MASTER_BRAINSTORM.md` append log
- [ ] Grok review §D/F items closed

---

## Related docs

- `docs/GROK_HEAVY_STRATEGY_REVIEW_2026-05-30.md` — strategy context
- `docs/OPERATOR_CODE_FREEZE_2026-05-30.md` — backlog §6 item 4
- `AI_CONTEXT.md` — learnings entry 30 May 2026 copy audit
