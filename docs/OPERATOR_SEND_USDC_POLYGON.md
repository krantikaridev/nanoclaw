# Send USDC to the bot wallet (Polygon) — beginner steps

You only need this if logs keep saying **`zero_usdc`**, **`USDC $0.00`**, or **`AUTO-USDC`** cannot top up during busy network periods. Putting **real USDC on Polygon** in the wallet lets BUY paths run without relying on swaps from USDT→USDC every time.

## What you are moving

- **Asset:** USDC (USD Coin).
- **Network:** **Polygon PoS** (sometimes labeled “Polygon”, “MATIC”, or “Polygon Mainnet”). It must **not** be Ethereum mainnet if your bot is configured for Polygon.
- **Recipient:** Your bot’s Polygon address — the line **`WALLET=0x...`** in **`~/.nanobot/workspace/nanoclaw/.env`**.

## Rough amount

- Aim for **$25–$40 USDC** on Polygon to clear typical floors (`~$20` safe floor / `$25` target in logs). More is fine; this is only a sensible minimum band.

---

## Path A — Use a centralized exchange (simplest if you already buy crypto there)

Steps are the same idea everywhere; wording may differ slightly per app.

1. Log in to the exchange web or app.
2. **Buy or hold USDC** (not “USDC on Ethereum” unless the next step asks for chain).
3. Open **Withdraw** / **Send** crypto.
4. Choose asset **USDC**.
5. Choose network **Polygon** (or **MATIC**) — confirm the UI explicitly says Polygon, not Ethereum.
6. Paste the **destination address**: copy **`WALLET`** from your VM `.env` (starts with `0x`). Double-check **first 6 and last 6 characters** after pasting (typo = lost funds).
7. Submit and wait for confirmations (often a few minutes).
8. Verify (next section).

---

## Path B — Use a self-custody wallet (e.g. MetaMask)

1. Install MetaMask (or similar) and create/restore a wallet **you control**.
2. **Add the Polygon network** if it is missing (MetaMask: add network → search “Polygon” / use Polygon’s official RPC details from their docs).
3. Obtain USDC **on Polygon**:
   - **Receive from elsewhere** using Path A withdrawal to **your MetaMask Polygon address**, or  
   - Use an **on-ramp** / **buy** inside the wallet if available, selecting **Polygon** as the receiving network where asked.
4. In MetaMask, ensure the **Polygon** network is selected (top dropdown).
5. Click **Send** → choose token **USDC** → paste the bot **`WALLET`** address from `.env` → confirm amount → send.
6. Verify (next section).

**Do not** send random tokens or unsupported “bridged” variants unless you know they match **`USDC=`** in `.env`. When unsure, use plain **USDC on Polygon**.

---

## Verify it arrived

1. Open [Polygonscan address lookup](https://polygonscan.com/) in a browser (replace with your **`WALLET`** address in the URL or search box):

   `https://polygonscan.com/address/YOUR_WALLET_ADDRESS`

2. Under **Token Holdings**, confirm **USD Coin (USDC)** shows a balance matching what you sent (minus tiny fees).

3. On the VM, wait for one bot cycle (or restart), then check:

   ```bash
   grep -E "WALLET BALANCE|WALLET TOTAL USD|USDC=\$|zero_usdc" ~/.nanobot/workspace/nanoclaw/real_cron.log | tail -n 30
   ```

   USDC balance in logs should climb above **`$0.00`** if RPC connectivity is healthy.

---

## Still seeing `USDC $0` in logs?

Then the bot likely **cannot read the chain** (bad RPC placeholder, or all endpoints failing). Fix **`RPC_ENDPOINTS` / `RPC` / `WEB3_PROVIDER_URI`** first using **`docs/readme-vm-update.md`** (section *Explicit checklist: RPC and `MAX_GWEI`*). Without a working RPC, on-chain balances look like zero.
