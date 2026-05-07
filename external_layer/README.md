# External Risk Layer

Standalone process that polls **Polygon wallet balances**, evaluates **risk tiers**, and writes repo-root **`control.json`** so **nanoclaw** can apply **`paused`**, **`max_copy_trade_pct`**, and an optional **`reason`** on each trading cycle.

## Purpose of External Risk Layer

This layer exists to:

- **Protect capital during bad regimes** (low balances / stressed conditions).
- **Prevent over-trading** by tightening copy sizing and, in critical cases, pausing new entries entirely.

It runs **out-of-band** from the bot so risk gates can update continuously without blocking the main trading loop.

## Current Risk Thresholds

The external layer currently tiers risk based on **either** USDT balance or WMATIC balance:

| Tier | Condition (either is enough) | Bot effect | Copy cap written to `control.json` |
|------|-------------------------------|------------|------------------------------------|
| **Critical** | **USDT < 60** **or** **WMATIC < 50** | **Paused** (no new entries) | **2%** (`0.02`) |
| **Moderate** | **USDT < 85** **or** **WMATIC < 65** | Not paused | **3%** (`0.03`) |
| **Healthy** | Otherwise | Not paused | **6%** (`0.06`) |

Notes:

- These values were **adjusted from stricter initial thresholds** after early observation/testing to reduce unnecessary pauses while still enforcing capital protection.
- The layer also includes a **defensive cooldown / clamp**: if the last **3** evaluations are in a protected tier (Critical or Moderate), it temporarily **clamps copy sizing to 2% for ~10 minutes**, even if the tier would otherwise allow 3%/6%.

## How to Run the External Layer (Recommended Way)

The external layer should run **alongside** `nanoclaw` as a separate long-lived process.

### Recommended: `screen` (detached)

From the repo root on the VM:

```bash
cd /path/to/nanoclaw
screen -S nc-ext -dm bash -lc './start_external.sh >> external_layer.log 2>&1'
```

### Check if it’s running

```bash
screen -ls
```

You should see a session like `nc-ext`. To attach:

```bash
screen -r nc-ext
```

To detach again: press `Ctrl+A` then `D`.

### Alternative: run foreground (local/dev)

```bash
python external_layer/control.py
```

Or (POSIX/bare VM helper):

```bash
./start_external.sh
```

The loop refreshes **`control.json` about every ~30 seconds** and prints `[EXTERNAL] ...` status lines.

## Useful Aliases (nc- prefix)

These aliases are intended for **fast operator monitoring** while the bot runs. Add them to your shell profile (e.g. `~/.bashrc`) on the VM.

| Alias | What it does |
|------|--------------|
| **`nc-health`** | Runs `nanohealth` from the repo root (quick RPC sanity check). |
| **`nc-full`** | Operator snapshot: `nanostatus` + current `control.json`. |
| **`nc-ext-status`** | Prints `control.json` (and file metadata) once. |
| **`nc-ext-watch`** | Live monitor of `control.json` (watch refresh cadence + fields). |
| **`nc-ext-start`** | Starts the external layer in a detached `screen` session (`nc-ext`). |
| **`nc-ext-attach`** | Attaches to the `screen` session for live `[EXTERNAL]` output. |
| **`nc-ext-stop`** | Stops the `screen` session (ends the external layer). |
| **`nc-ext-log`** | Tails `external_layer.log` (if you started with log redirection). |

```bash
# External layer: watch the control file update live
alias nc-ext-status='cd /path/to/nanoclaw && ls -la control.json && cat control.json'
alias nc-ext-watch='cd /path/to/nanoclaw && watch -n 2 "cat control.json"'

# “Full picture” monitoring (bot + PnL + health)
alias nc-health='cd /path/to/nanoclaw && nanohealth'
alias nc-full='cd /path/to/nanoclaw && nanostatus && echo && cat control.json'

# External layer lifecycle helpers (screen-based)
alias nc-ext-start='cd /path/to/nanoclaw && screen -S nc-ext -dm bash -lc "./start_external.sh >> external_layer.log 2>&1" && screen -ls | grep -F nc-ext || true'
alias nc-ext-attach='screen -r nc-ext'
alias nc-ext-stop='screen -S nc-ext -X quit && screen -ls'
alias nc-ext-log='cd /path/to/nanoclaw && tail -n 200 -f external_layer.log'
```

If you created additional `nc-*` aliases in your environment (for example `nc-ext-restart`, `nc-ext-log`, etc.), keep them in the same section and follow the naming convention:

- **`nc-ext-*`**: external-layer operations / control-file inspection
- **`nc-*`**: operator convenience wrappers (health, combined status views)

## Monitoring Workflow

Recommended steady-state monitoring:

- **`nc-ext-watch`**: watch `control.json` update and confirm the layer is alive (`last_updated` moves).
- **`nc-full`**: quick “operator snapshot” combining bot status and the external-layer control state.

What to look for:

- **Paused state**: `paused=true` means **no new entries** (copy + main). Protective exits still run.
- **Balance telemetry**: `usdt_balance` / `wmatic_balance` should look sane and move with reality.
- **Protection triggers**: `reason` should clearly indicate which tier is active and whether the defensive clamp is active.
- **Staleness**: if `last_updated` stops advancing, the external layer is down or stuck (or the process lost `.env` / RPC access).

## What `control.json` does

`control.json` is the contract between the external layer and the bot.

| Field | Role |
|--------|------|
| **`paused`** | When `true`, **nanoclaw skips new entries** (copy and main strategy); protective exits still run. |
| **`max_copy_trade_pct`** | Caps copy-trade sizing when present; otherwise **`COPY_TRADE_PCT`** from `.env` applies. |
| **`reason`** | Operator-facing explanation (logged / skip messages). |
| **`last_updated`** | UTC timestamp of the last write (used as a liveness check). |
| **`usdt_balance`**, **`wmatic_balance`** | Echo of the last successful reads (informational). |

If **`control.json`** is **missing or invalid**, `load_cycle_control()` returns defaults (`paused=false`, no max override) and **nanoclaw falls back to `.env`** behavior.

## Current Known Limitation (as of May 2026)

When **USDT stays just below the Critical threshold** for long periods (e.g., hovering below 60), the layer can become **too defensive**:

- The bot can remain **paused for many hours**, resulting in **very few new entries**.
- Protection continues to trigger as designed, but **new trading activity is heavily restricted**.

This is currently expected behavior given the tier definition; it’s a trade-off between capital protection and opportunity capture.

## Recent Changes Made

- **Initial strict thresholds** were applied early on.
- Thresholds were **slightly loosened** after observation to reduce unnecessary halts while still enforcing protection.
- **Defensive cooldown/clamp logic** was added to reduce over-trading after repeated low-balance evaluations (temporary clamp to 2% sizing after repeated protected-tier hits).

## Troubleshooting

- **RPC / balance read fails**: the loop logs a **WARNING**, keeps the **last successful** pause/size state when possible, or writes a **heartbeat** that bumps `last_updated` while preserving existing `paused`/`reason`. The bot keeps running; verify **`nanohealth`** and RPC endpoints in `.env`.
- **Nothing changes in `control.json`**: confirm `./start_external.sh` (or `python external_layer/control.py`) is running, `WALLET=` matches the intended address, and stdout shows `[EXTERNAL]` lines.
- **Stop the external layer**: `Ctrl+C` in the foreground terminal, or `kill` the PID / stop the `screen` session. Stopping the external layer does **not** stop nanoclaw; `control.json` just stops updating until restart.

## See also

- `modules/swap_executor.py` — reads `control.json` each cycle via `load_cycle_control`.
- Repo `README.md` — high-level mention of the external layer and `control.json`.
