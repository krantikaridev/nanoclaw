# External Risk Layer

Standalone process that polls **Polygon wallet balances** (USDT, **combined USDC**, and WMATIC), evaluates **risk tiers**, and writes the repo-root **`control.json`** so that **nanoclaw** can dynamically apply **`paused`**, **`max_copy_trade_pct`**, and an optional **`reason`** on each trading cycle.

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

### Design principle: no manual intervention

The External Risk Layer should **not force operators to babysit wallets**—for example, manually swapping quote assets so a single-stable rule stays green. Thresholds align with **spendable stable runway as the bot understands it**: **total stables ≈ USDT + USDC** (USDC.e from `USDC=` plus native Polygon USDC from `USDC_NATIVE=` when that is a distinct contract—the same aggregation as **`STABLE_USD`** / `_total_usdc_balance` in **`modules/runtime.py`**). Gas runway remains tied to **WMATIC** thresholds.

### Real incident (2026-05-07)

Production saw **`paused: true`** because **USDT went to $0** while **USDT + USDC** was still **healthy** (~$83+). The previous rule treated “low USDT” as critical even when **USDC** could still fund USDC-copy and related paths. **External risk now keys off total stables** for those USD tiers so this class of stuck state cannot recur from USDT‑only drain.

## Current Risk Thresholds

Risk tier is determined by **either** **`stable_usd` (USDT + combined USDC)** **or** the **WMATIC** balance falling below defined levels (whichever triggers first — conservative “or” logic). WMATIC checks are unchanged.

| Tier      | Condition                                      | Bot Behavior                          | `max_copy_trade_pct` written to `control.json` | Notes |
|-----------|------------------------------------------------|---------------------------------------|------------------------------------------------|-------|
| **Critical** | (`USDT` + combined `USDC`) < **60** **or** WMATIC < **50** | **Paused** (no new entries)          | **2%** (`0.02`)                               | Strongest protection. New copy trades and main strategy entries are skipped. Protective exits still execute. |
| **Moderate** | (`USDT` + combined `USDC`) < **85** **or** WMATIC < **65** | Not paused                           | **3%** (`0.03`)                               | Reduced sizing to conserve capital while still allowing some activity. |
| **Healthy**  | Total stables ≥ **85** **and** WMATIC ≥ **65** | Not paused                    | **6%** (`0.06`)                               | Normal / full sizing allowed (subject to other strategy rules). |

### Additional defensive clamp logic
- The layer tracks the last several risk evaluations (using a short rolling window).
- If the **last 3 evaluations** were in a protected tier (Critical or Moderate), it activates a **temporary defensive clamp**: forces `max_copy_trade_pct = 2%` for approximately **10 minutes**, even if the current balances would otherwise allow 3% or 6%.
- **Clamp adjustment:** when **`stable_usd` recovers to ≥ 85**, the timer clears and the 2% streak clamp stops immediately (no need to wait the full ~10 minutes); if combined stables are still below **85** but the **stable-runway tier** (critical vs moderate bands on total stables) is **strictly better** than the worst stable level in the arming streak, the layer keeps the **tier** copy cap (e.g. 3% in moderate) instead of forcing 2%.
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
   - `usdt_balance`, **`usdc_balance`** (combined USDC buckets), **`stable_usd`** (USDT + that combined USDC), and `wmatic_balance` reflecting reality.

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
| `paused: true` + reason mentions Critical | Total stables (USDT+USDC) or WMATIC below critical threshold | Monitor recovery; top up stables or WMATIC on-chain if prolonged. |
| `max_copy_trade_pct: 0.03`     | Moderate tier active                        | Normal during mild stress; watch for improvement. |
| `reason` contains "defensive clamp" | Recent streak of low-balance readings      | Temporary; relaxes after ~10 min, or immediately once **`stable_usd` ≥ 85**. |
| `last_updated` not advancing   | External layer stopped or RPC failure      | Restart with `nc-ext-start`; check logs and `nanohealth`. |

## Current known limitations

- **Defensive clamp (10 min after 3 protected-tier reads)** still tightens **`max_copy_trade_pct`** temporarily; pairing with tier changes can feel conservative briefly after stress.
- **Hard numeric thresholds**: no hysteresis on **pause/unpause** (only on copy cap via clamp). Truly depleted wallets (combined stables below **$60** **or** WMATIC below **50**) still pause until on-chain balances recover—by design.

The previous issue where **USDT-only** rules paused the bot despite **healthy USDT+USDC** is addressed by **total-stables tiers** (see incident above).

## Recent changes made during development

- **Initial strict thresholds** were implemented in the first version of `risk_checker.py` (higher Critical values led to frequent pauses even in moderate conditions).
- Thresholds were **slightly loosened** (to the current **stable** 60/85 and WMATIC 50/65 levels) after real-world testing and observation showed unnecessary halts that reduced overall trading activity.
- **2026-05-07**: USD tiers now use **`stable_usd` = USDT + combined USDC** (USDC.e + native when distinct) instead of USDT alone, matching runtime **STABLE_USD** semantics and preventing false critical pauses when only USDT is drained.
- **Defensive cooldown / clamp logic** was added to `evaluate_risk()`: after 3 consecutive protected-tier evaluations, a 10-minute forced 2% cap is applied. This reduces whiplash and over-trading when balances fluctuate near boundaries.
- Created a full set of convenient **`nc-*` aliases** for rapid monitoring and screen-based lifecycle management (`nc-ext-start`, `nc-ext-watch`, `nc-full`, etc.).
- Improved `control.json` payload with live balance echo fields (`usdt_balance`, **`usdc_balance`**, **`stable_usd`**, `wmatic_balance`) and robust heartbeat behavior on RPC failures (preserves last known `paused`/`reason` while updating `last_updated`).
- Documentation (this README) expanded with practical workflows, limitation transparency, and operator guidance.

## What `control.json` Does (Contract Between Layer and Bot)

| Field                | Purpose                                                                 | Example Value      |
|----------------------|-------------------------------------------------------------------------|--------------------|
| `paused`             | When `true`, nanoclaw skips **new entries** (copy trades + main strategy). Protective exits still run. | `true` or `false` |
| `max_copy_trade_pct` | Caps the size of copy trades for this cycle (overrides `COPY_TRADE_PCT` from `.env` when present). | `0.02`, `0.03`, or `0.06` |
| `reason`             | Human-readable explanation of the current risk decision (appears in logs and skip messages). | `"Moderate … (USDT+USDC<85 …)"` |
| `last_updated`       | UTC ISO timestamp of the last successful write (primary liveness indicator). | `"2026-05-07T15:12:03Z"` |
| `usdt_balance`       | Last successfully read USDT balance (informational / debugging).       | `54.23` |
| `usdc_balance`       | Last successfully read **combined** USDC (USDC.e + native USDC when different contracts). | `82.81` |
| `stable_usd`         | **USDT + `usdc_balance`** — mirrors what the tier logic uses for USD runway. | `137.04` |
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
