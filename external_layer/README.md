# External Risk Layer

Standalone process that polls **Polygon wallet balances** (USDT and WMATIC), evaluates **risk tiers**, and writes the repo-root **`control.json`** so that **nanoclaw** can dynamically apply **`paused`**, **`max_copy_trade_pct`**, and an optional **`reason`** on each trading cycle.

The layer runs **out-of-band** (separate process) from the main bot. This allows risk gates to update continuously (~every 30 seconds) without blocking or slowing down the trading loop.

## Purpose of the External Risk Layer

The External Risk Layer exists to:

- **Protect capital during stressed or low-balance regimes** — e.g., after a series of losing trades, high gas costs, or market drawdowns that leave the wallet with insufficient reserves.
- **Prevent over-trading and excessive risk exposure** by automatically tightening copy-trade sizing and, in critical cases, completely pausing new entries (while still allowing protective exits).
- Provide a **decoupled, observable control plane** — operators and future agents can inspect or even manually override `control.json` without touching the core trading code or `.env`.

By externalizing risk decisions, the system gains:
- Better separation of concerns (risk logic vs. execution logic).
- Easier tuning of thresholds without redeploying the bot.
- Live visibility into why the bot is behaving conservatively (`reason` field).

## Current Risk Thresholds

Risk tier is determined by **either** the USDT balance **or** the WMATIC balance falling below defined levels (whichever triggers first — conservative “or” logic).

| Tier      | Condition                                      | Bot Behavior                          | `max_copy_trade_pct` written to `control.json` | Notes |
|-----------|------------------------------------------------|---------------------------------------|------------------------------------------------|-------|
| **Critical** | USDT < **60** **or** WMATIC < **50**          | **Paused** (no new entries)          | **2%** (`0.02`)                               | Strongest protection. New copy trades and main strategy entries are skipped. Protective exits still execute. |
| **Moderate** | USDT < **85** **or** WMATIC < **65**          | Not paused                           | **3%** (`0.03`)                               | Reduced sizing to conserve capital while still allowing some activity. |
| **Healthy**  | Neither condition met (USDT ≥ 85 **and** WMATIC ≥ 65) | Not paused                    | **6%** (`0.06`)                               | Normal / full sizing allowed (subject to other strategy rules). |

### Additional Defensive Clamp Logic
- The layer tracks the last several risk evaluations (using a short rolling window).
- If the **last 3 evaluations** were in a protected tier (Critical or Moderate), it activates a **temporary defensive clamp**: forces `max_copy_trade_pct = 2%` for approximately **10 minutes**, even if the current balances would otherwise allow 3% or 6%.
- Reason string includes: `"defensive clamp active (recent low-balance streak)"`.
- This adds a form of hysteresis to avoid rapid toggling when balances hover near thresholds.

**Why these numbers?**  
They were chosen to leave headroom for gas fees (WMATIC/MATIC on Polygon), potential exit transactions, and a small buffer for recovery. The values were **slightly loosened from stricter initial thresholds** after early testing showed excessive pausing.

## How to Run It (Recommended Way)

The external layer should run **continuously alongside** `nanoclaw` as a long-lived background process.

### Recommended: Detached `screen` Session

From the repository root on your VM:

```bash
cd /path/to/nanoclaw
screen -S nc-ext -dm bash -lc './start_external.sh >> external_layer.log 2>&1'
```

- This starts the Python loop in a detached screen named `nc-ext`.
- All output (including `[EXTERNAL] ...` status lines) is redirected to `external_layer.log`.

### Verify It Is Running

```bash
screen -ls
```

You should see something like:
```
There is a screen on:
        12345.nc-ext    (Detached)
```

To attach and watch live output:
```bash
screen -r nc-ext
```
Detach again with `Ctrl+A` then `D`.

### Alternative: Foreground (for local dev / debugging)

```bash
python external_layer/control.py
```

Or using the helper:
```bash
./start_external.sh
```

The control loop refreshes `control.json` approximately every **30 seconds** and prints status lines prefixed with `[EXTERNAL]`.

## Useful Aliases (`nc-*` prefix)

These aliases provide **fast operator monitoring** and lifecycle control. Add them to your shell profile (`~/.bashrc`, `~/.bash_aliases`, or `~/.zshrc`) on the VM and reload (`source ~/.bashrc`).

**Important:** Replace `/path/to/nanoclaw` with your actual repository path (e.g. `$HOME/nanoclaw` or `/opt/nanoclaw`).

```bash
# === External layer file inspection ===
alias nc-ext-status='cd /path/to/nanoclaw && ls -la control.json && cat control.json'
alias nc-ext-watch='cd /path/to/nanoclaw && watch -n 2 "cat control.json"'

# === Combined operator snapshot (bot health + external control) ===
alias nc-health='cd /path/to/nanoclaw && nanohealth'
alias nc-full='cd /path/to/nanoclaw && nanostatus && echo && cat control.json'

# === External layer lifecycle (screen-based) ===
alias nc-ext-start='cd /path/to/nanoclaw && screen -S nc-ext -dm bash -lc "./start_external.sh >> external_layer.log 2>&1" && screen -ls | grep -F nc-ext || true'
alias nc-ext-attach='screen -r nc-ext'
alias nc-ext-stop='screen -S nc-ext -X quit && screen -ls'
alias nc-ext-log='cd /path/to/nanoclaw && tail -n 200 -f external_layer.log'
```

You can extend with additional helpers (e.g. `nc-ext-restart`) following the `nc-ext-*` naming convention for external-layer operations.

## Monitoring Workflow

### Steady-State Recommended Workflow

1. **Start / ensure running**
   ```bash
   nc-ext-start
   ```

2. **Live monitor the control file** (best for seeing tier changes in real time)
   ```bash
   nc-ext-watch
   ```
   Watch for:
   - `last_updated` timestamp advancing every ~30s (liveness).
   - `paused` flipping to `true` / `false`.
   - `reason` explaining the current tier or clamp.
   - `usdt_balance` and `wmatic_balance` reflecting reality.

3. **Quick combined view** (bot status + risk control)
   ```bash
   nc-full
   ```

4. **Investigate when paused or heavily restricted**
   - Check actual wallet balances (via `nc-health` or Polygon explorer).
   - Look at the `reason` field in `control.json`.
   - Review recent `[EXTERNAL]` logs: `nc-ext-log | tail -100`.

### What to Look For

| Observation                    | Likely Meaning                              | Recommended Action |
|--------------------------------|---------------------------------------------|--------------------|
| `paused: true` + reason mentions Critical | USDT or WMATIC below critical threshold    | Monitor recovery; consider manual top-up if prolonged. |
| `max_copy_trade_pct: 0.03`     | Moderate tier active                        | Normal during mild stress; watch for improvement. |
| `reason` contains "defensive clamp" | Recent streak of low-balance readings      | Temporary; will relax after ~10 min if balances stay healthy. |
| `last_updated` not advancing   | External layer stopped or RPC failure      | Restart with `nc-ext-start`; check logs and `nanohealth`. |

## Current Known Limitation (Over-Protection When Hovering Near Threshold)

**As of May 2026**, the layer can become **too defensive** when USDT balance **stays just below the Critical threshold ($60)** for extended periods:

- The bot may remain **paused for many hours** with almost **no new entries**.
- Even if market conditions improve and PnL recovery would benefit from scaling in, the strict tier definition keeps `paused=true` and copy sizing at 2%.
- This **hurts PnL recovery** by preventing the bot from participating in favorable moves while capital is still low but not yet critically depleted.

**Why it happens**: The current design uses hard thresholds with no built-in hysteresis or time-decay. A balance that oscillates or slowly climbs just under $60 triggers continuous Critical state. The defensive clamp further extends the conservative period.

**Trade-off**: Excellent capital protection during true stress, but can overly restrict opportunity capture during the early stages of wallet recovery.

This limitation is acknowledged and may be addressed in future iterations (possible ideas: multi-level hysteresis, temporary “recovery mode” after prolonged pause, or dynamic thresholds based on recent PnL trajectory). For now, operators should be aware that manual intervention (topping up USDT/WMATIC or temporarily editing `control.json`) may be needed in prolonged near-threshold scenarios.

## Recent Changes Made During Development

- **Initial strict thresholds** were implemented in the first version of `risk_checker.py` (higher Critical values led to frequent pauses even in moderate conditions).
- Thresholds were **slightly loosened** (to the current USDT 60/85 and WMATIC 50/65 levels) after real-world testing and observation showed unnecessary halts that reduced overall trading activity.
- **Defensive cooldown / clamp logic** was added to `evaluate_risk()`: after 3 consecutive protected-tier evaluations, a 10-minute forced 2% cap is applied. This reduces whiplash and over-trading when balances fluctuate near boundaries.
- Created a full set of convenient **`nc-*` aliases** for rapid monitoring and screen-based lifecycle management (`nc-ext-start`, `nc-ext-watch`, `nc-full`, etc.).
- Improved `control.json` payload with live balance echo fields (`usdt_balance`, `wmatic_balance`) and robust heartbeat behavior on RPC failures (preserves last known `paused`/`reason` while updating `last_updated`).
- Documentation (this README) expanded with practical workflows, limitation transparency, and operator guidance.

## What `control.json` Does (Contract Between Layer and Bot)

| Field                | Purpose                                                                 | Example Value      |
|----------------------|-------------------------------------------------------------------------|--------------------|
| `paused`             | When `true`, nanoclaw skips **new entries** (copy trades + main strategy). Protective exits still run. | `true` or `false` |
| `max_copy_trade_pct` | Caps the size of copy trades for this cycle (overrides `COPY_TRADE_PCT` from `.env` when present). | `0.02`, `0.03`, or `0.06` |
| `reason`             | Human-readable explanation of the current risk decision (appears in logs and skip messages). | `"CRITICAL: USDT balance 54.2 < 60"` |
| `last_updated`       | UTC ISO timestamp of the last successful write (primary liveness indicator). | `"2026-05-07T15:12:03Z"` |
| `usdt_balance`       | Last successfully read USDT balance (informational / debugging).       | `54.23` |
| `wmatic_balance`     | Last successfully read WMATIC balance (informational / debugging).     | `48.7` |

**Fallback behavior**: If `control.json` is missing, empty, or invalid, `load_cycle_control()` returns safe defaults (`paused=false`, no max override). The bot falls back to `.env` configuration.

## Troubleshooting

- **RPC or balance read failures**: The layer logs a WARNING, keeps the **last successful** `paused`/`reason` state when possible, and still bumps `last_updated` (heartbeat). The bot continues running. Verify with `nc-health` and check RPC URLs / `WALLET` in `.env`.
- **`control.json` not updating**: Confirm the screen session is alive (`screen -ls`), the process is printing `[EXTERNAL]` lines, and `WALLET` address is correct. Check file permissions on repo root.
- **Stopping the layer**: Use `nc-ext-stop` or `screen -S nc-ext -X quit`. Stopping the external layer does **not** stop nanoclaw — `control.json` simply stops being refreshed until the layer restarts.
- **Stale `last_updated`**: External layer is likely down or has lost connectivity. Restart it and investigate logs.

## See Also

- `external_layer/control.py` — orchestration, JSON I/O, and integration with risk evaluation.
- `external_layer/risk_checker.py` — core `evaluate_risk()` logic, balance fetching via Web3, tier decisions, and defensive clamp.
- Main nanoclaw trading loop (how `load_cycle_control()` is called on each cycle).
- Project root `start_external.sh` — simple launcher script.

---

*This documentation reflects the state of the External Risk Layer as of May 2026. Thresholds and behavior are subject to tuning based on ongoing live trading results and PnL analysis.*
