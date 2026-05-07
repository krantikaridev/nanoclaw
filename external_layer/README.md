# External Risk Layer

Standalone process that polls Polygon wallet balances, evaluates risk tiers, and writes repo-root **`control.json`** so **`nanoclaw`** can apply **`paused`**, **`max_copy_trade_pct`**, and optional **`reason`** on each trading cycle.

## Run standalone (local or VM)

From the repository root (requires `.env` / RPC / `WALLET=` like the main bot):

```bash
python external_layer/control.py
```

Or use the repo helper script (POSIX / bash on the stage VM):

```bash
chmod +x start_external.sh   # once per checkout if needed
./start_external.sh
```

The loop prints status lines and refreshes **`control.json`** about every **30 seconds**.

## Run alongside nanoclaw on the VM (recommended)

1. Deploy the repo as usual (`nanoup` or your normal pull + env sync).
2. Run **`nanoclaw`** with your existing cron/systemd flow (`nanoup` starts the bot).
3. In a **separate** terminal session or a second **`systemd` user unit**, start the external layer so it keeps **`control.json`** fresh while the bot runs:

   ```bash
   cd /path/to/nanoclaw
   ./start_external.sh
   ```

   Use **`screen`**, **`tmux`**, or a dedicated service so the process survives SSH disconnects. The external layer only needs the same **`.env`** visibility as the bot (working directory at repo root is recommended).

**Why two processes?** The bot focuses on execution; this layer focuses on risk gates and copy-trade caps from live balances without blocking the trading loop.

## What `control.json` does

| Field | Role |
|--------|------|
| **`paused`** | When `true`, **`nanoclaw`** skips **new entries** (copy and main strategy); protective exits still run. |
| **`max_copy_trade_pct`** | Caps copy-trade sizing when present; otherwise **`COPY_TRADE_PCT`** from `.env` applies. |
| **`reason`** | Operator-facing text (logged / skipped-trade messages). |
| **`last_updated`** | UTC timestamp of the last write (helps verify the external layer is alive). |
| **`usdt_balance`**, **`wmatic_balance`** | Echo of last successful reads (informational). |

If **`control.json`** is **missing or invalid**, **`load_cycle_control()`** returns defaults (`paused=false`, no max override)—**`nanoclaw`** falls back to **`.env`** behavior.

## Troubleshooting

- **RPC / balance read fails:** The loop logs a **WARNING**, keeps the **last successful** pause/size state when possible, or writes a **heartbeat** that bumps **`last_updated`** while preserving existing **`paused`** / **`reason`**. The bot keeps running; verify **`nanohealth`** and RPC endpoints in **`.env`**.
- **Nothing changes in `control.json`:** Confirm **`./start_external.sh`** or **`python external_layer/control.py`** is running, **`WALLET=`** matches the intended address, and stdout shows **`[EXTERNAL]`** lines.
- **Stop the external layer:** **`Ctrl+C`** in the terminal, or **`kill`** the PID / stop the **`systemd`** unit. Stopping this process does **not** stop **`nanoclaw`**; **`control.json`** simply stops updating until you restart the layer or edit the file manually.

## See also

- **`modules/swap_executor.py`** — reads **`control.json`** each cycle via **`load_cycle_control`**.
- Repo **`README.md`** — high-level mention of the external layer and **`control.json`**.
