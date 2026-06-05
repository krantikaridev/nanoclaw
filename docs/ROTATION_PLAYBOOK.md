# Rotation playbook — safe swap caps by book size

Dev/lab reference for **V4-play** and small-book VMs. Stage wallet `0x05eF…` stays on **V2 paused** until a separate 48h lab gate passes.

All figures are **spot swaps on Polygon** (no leverage). Protection exits (derisk, rebuild, loss-cut) may use their own caps and are not limited here.

## Safe swap table

| Book (TOTAL) | Per-swap cap | Stables floor after buy | Max entry fills / UTC day | Unpause rule |
|--------------|--------------|-------------------------|---------------------------|--------------|
| **~$80** | **$8** | **≥ $20** | **2** (`PLAY_BUDGET_*`) | 8h **and** 12h window PASS, session ≥ −1%, pause_exec PASS |
| **~$135** | **$8–10** | **≥ $25** | **2** | Same dual-window gate |
| **~$200** | **$10** | **≥ $30** | **2** (budget off when TOTAL ≥ $200) | Same dual-window gate |

### Play types

| Play | Direction | Typical cap | Gates |
|------|-----------|-------------|-------|
| High-stable WMATIC rotation | USDC → WMATIC | $10 (`MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_NOTIONAL_USD`) | Stables ≥ $30, FE share < 80%, signal ≥ 0.85 |
| Tiered runway buy | USDC → equity | $8–10 (`FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD`) | 4h cooldown after fill/rebuild |
| X-Signal equity | USDC → equity | **$10** when 12h window < 0% (`X_SIGNAL_NEGATIVE_WINDOW_MAX_TRADE_USD`); else template max ($28) | `PLAY_BUDGET` on books < $200 |
| Window-stress derisk | equity → USDC | ~$12 trim | Only when paused for window PnL; FE share ≥ 72% |

## V4-play env knobs (lab VM)

```bash
# Dual-window unpause (default on V4-play)
EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW=true
EXTERNAL_AUTO_UNPAUSE_SHORT_HOURS=8
EXTERNAL_AUTO_GREEN_HOURS=12
EXTERNAL_AUTO_WINDOW_MIN_PCT=-2.0

# Entry budget — small books only
PLAY_BUDGET_ENABLED=true
PLAY_BUDGET_MAX_FILLS_PER_UTC_DAY=2
PLAY_BUDGET_TOTAL_USD_CEILING=200

# Negative-window X-SIGNAL cap
X_SIGNAL_NEGATIVE_WINDOW_CAP_ENABLED=true
X_SIGNAL_NEGATIVE_WINDOW_MAX_TRADE_USD=10
```

## Operator checks

```bash
python scripts/nano_green.py --hours 12
python scripts/nano_green.py --hours 8
grep "$(date -u +%Y-%m-%d)" real_cron.log | grep -c 'EXEC SUCCESS'
grep 'PLAY BUDGET' real_cron.log | tail -5
```

## Merge to stage checklist

- Lab VM **48h** with **≤ 4 fills/day** and window stable
- `nano12h` PASS on lab before any deploy to `0x05eF…`
- **Zero** `nanodeploy` to stage from `V4-play` until parent sign-off
