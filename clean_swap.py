from v25_protection import check_exit_conditions, record_buy, get_live_wmatic_price
from v25_copy_trading import get_target_wallets, get_copy_ratio
from brain_agent import BrainAgent
import os
import time
import sys
import asyncio
import json
from web3 import Web3
from dotenv import load_dotenv
from constants import WALLET, USDT, WMATIC, ROUTER, ROUTER_ABI, ERC20_ABI
from nanoclaw.utils.gas_protector import GasProtector
from swap_executor import approve_and_swap

load_dotenv()

LOCK_FILE = "/tmp/nanoclaw.lock"
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", 7))
MIN_POL_FOR_GAS = float(os.getenv("MIN_POL_FOR_GAS", "0.05"))
COPY_TRADE_PCT = float(os.getenv("COPY_TRADE_PCT", "0.12"))
PER_WALLET_COOLDOWN = int(os.getenv("PER_WALLET_COOLDOWN", "300"))

w3 = Web3(Web3.HTTPProvider(os.getenv("RPC")))
GAS_PROTECTOR = (
    GasProtector.builder()
    .with_max_gwei(float(os.getenv("MAX_GWEI", "80")))
    .with_urgent_gwei(float(os.getenv("URGENT_GWEI", "120")))
    .with_min_pol_balance(MIN_POL_FOR_GAS)
    .with_primary_rpc(os.getenv("RPC"))
    .with_fallback_rpcs(os.getenv("RPC_FALLBACKS", "").split(","))
    .with_retry_attempts(int(os.getenv("GAS_RPC_RETRY_ATTEMPTS", "2")))
    .build()
)

# ==================== v2.6.2 TRAILING STOP + DYNAMIC TP ====================
PEAK_PRICE = 0.0
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "5.0"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "8.0"))
STRONG_SIGNAL_TP = float(os.getenv("STRONG_SIGNAL_TP", "12.0"))
TAKE_PROFIT_SELL_PCT = float(os.getenv("TAKE_PROFIT_SELL_PCT", "0.45"))
STRONG_TP_SELL_PCT = float(os.getenv("STRONG_TP_SELL_PCT", "0.60"))
TRADE_LOG_FILE = "trade_exits.json"

def check_trailing_stop(current_price):
    global PEAK_PRICE
    if PEAK_PRICE == 0:
        PEAK_PRICE = current_price
    if current_price > PEAK_PRICE:
        PEAK_PRICE = current_price
    drop = (PEAK_PRICE - current_price) / PEAK_PRICE * 100
    if drop >= TRAILING_STOP_PCT:
        return True, f"Trailing stop triggered ({drop:.1f}% drop from peak)"
    return False, ""

# ==================== v2.6.3 AUTO-SCALE TRADE SIZE ====================
def get_dynamic_trade_size(usdt_balance):
    pct = 0.12
    size = usdt_balance * pct
    return max(8.0, min(30.0, size))
# ==================== v2.6 PER-WALLET COOLDOWN ====================
WALLET_LAST_TRADE = {}

def can_trade_wallet(wallet_address):
    last = WALLET_LAST_TRADE.get(wallet_address, 0)
    return (time.time() - last) > PER_WALLET_COOLDOWN

def mark_wallet_traded(wallet_address):
    WALLET_LAST_TRADE[wallet_address] = time.time()
    print(f"📌 Wallet {wallet_address[:8]}... cooldown started ({PER_WALLET_COOLDOWN}s)")

def get_token_balance(token_address: str, decimals: int = 6) -> float:
    try:
        contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return contract.functions.balanceOf(WALLET).call() / (10 ** decimals)
    except:
        return 0.0

def get_pol_balance():
    return GAS_PROTECTOR.get_pol_balance(WALLET)


def get_gas_status(urgent=False):
    return GAS_PROTECTOR.get_safe_status(
        address=WALLET,
        urgent=urgent,
        min_pol=MIN_POL_FOR_GAS,
    )

def load_state():
    try:
        with open('bot_state.json', 'r') as f:
            return json.load(f)
    except:
        return {"last_run": 0}

def save_state(state):
    with open('bot_state.json', 'w') as f:
        json.dump(state, f, indent=2)

def get_latest_open_trade():
    if not os.path.exists(TRADE_LOG_FILE):
        return None

    try:
        with open(TRADE_LOG_FILE, "r") as f:
            trades = json.load(f)
    except Exception:
        return None

    open_trades = [trade for trade in trades if trade.get("status") == "OPEN" and trade.get("buy_price")]
    if not open_trades:
        return None

    return open_trades[-1]

def evaluate_take_profit(current_price, state):
    trade = get_latest_open_trade()
    tracking = state.setdefault("profit_tracking", {})

    if not trade:
        tracking.clear()
        return False, None

    buy_price = float(trade["buy_price"])
    if buy_price <= 0:
        tracking.clear()
        return False, None

    tracked_buy_price = float(tracking.get("buy_price", 0) or 0)
    if tracked_buy_price != buy_price:
        tracking.clear()
        tracking["buy_price"] = buy_price
        tracking["peak_price"] = max(current_price, buy_price)

    peak_price = max(float(tracking.get("peak_price", buy_price)), current_price, buy_price)
    tracking["buy_price"] = buy_price
    tracking["peak_price"] = peak_price

    gain_pct = ((current_price - buy_price) / buy_price) * 100
    peak_gain_pct = ((peak_price - buy_price) / buy_price) * 100
    pullback_pct = ((peak_price - current_price) / peak_price) * 100 if peak_price > 0 else 0.0

    if gain_pct >= STRONG_SIGNAL_TP:
        return True, {
            "reason": "STRONG_TP_HIT",
            "message": (
                f"Strong TP hit | buy ${buy_price:.4f} -> now ${current_price:.4f} "
                f"({gain_pct:.2f}%) >= {STRONG_SIGNAL_TP:.2f}%"
            ),
            "sell_fraction": STRONG_TP_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    if gain_pct >= TAKE_PROFIT_PCT:
        return True, {
            "reason": "TP_HIT",
            "message": (
                f"Take-profit hit | buy ${buy_price:.4f} -> now ${current_price:.4f} "
                f"({gain_pct:.2f}%) >= {TAKE_PROFIT_PCT:.2f}%"
            ),
            "sell_fraction": TAKE_PROFIT_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    if peak_gain_pct >= TAKE_PROFIT_PCT and pullback_pct >= TRAILING_STOP_PCT:
        return True, {
            "reason": "TRAILING_STOP_HIT",
            "message": (
                f"Trailing stop hit | peak ${peak_price:.4f} ({peak_gain_pct:.2f}%) -> "
                f"now ${current_price:.4f} ({pullback_pct:.2f}% off peak)"
            ),
            "sell_fraction": TAKE_PROFIT_SELL_PCT,
            "gain_pct": gain_pct,
            "peak_gain_pct": peak_gain_pct,
            "pullback_pct": pullback_pct,
        }

    return False, {
        "reason": "HOLD",
        "message": (
            f"Holding open trade | buy ${buy_price:.4f} -> now ${current_price:.4f} "
            f"({gain_pct:.2f}%), peak ${peak_price:.4f} ({peak_gain_pct:.2f}%)"
        ),
        "sell_fraction": 0.0,
        "gain_pct": gain_pct,
        "peak_gain_pct": peak_gain_pct,
        "pullback_pct": pullback_pct,
    }

async def main():
    state = load_state()
    direction = None
    amount_in = 0
    trade_size = 0.0
    usdt_balance = get_token_balance(USDT, 6)
    wmatic_balance = get_token_balance(WMATIC, 18)
    pol = get_pol_balance()

    print(f"Real USDT: {usdt_balance:.2f} | WMATIC: {wmatic_balance:.2f} | POL: {pol:.2f}")

    if os.path.exists(LOCK_FILE) and (time.time() - os.path.getmtime(LOCK_FILE) < 15):
        print("⛔ Lock active — skipping")
        return
    open(LOCK_FILE, 'w').close()

    if time.time() - state.get("last_run", 0) < COOLDOWN_MINUTES * 60:
        print(f"⏳ Copy cooldown active (90s) — skipping")
        return

    gas_status = get_gas_status()
    if not gas_status["ok"]:
        print(
            "⛔ Gas protection active "
            f"(gas {gas_status['gas_gwei']:.2f}/{gas_status['max_gwei']:.2f} gwei, "
            f"POL {gas_status['pol_balance']:.4f}/{gas_status['min_pol_balance']:.4f})"
        )
        return

    # V2.5.1 Protection
    should_force_sell, reason = check_exit_conditions()
    if should_force_sell:
        direction = "WMATIC_TO_USDT"
        sell_fraction = 0.45
        current_price = get_live_wmatic_price()
        open_trade = get_latest_open_trade()
        if reason == "PER_TRADE_EXIT" and open_trade:
            buy_price = float(open_trade["buy_price"])
            gain_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
            sell_fraction = STRONG_TP_SELL_PCT if gain_pct >= STRONG_SIGNAL_TP else TAKE_PROFIT_SELL_PCT
            amount_in = int(wmatic_balance * sell_fraction * 1e18)
            print(
                f"🛡️ PROTECTION EXIT: {'strong TP hit' if gain_pct >= STRONG_SIGNAL_TP else 'TP hit'} | "
                f"buy ${buy_price:.4f} -> now ${current_price:.4f} "
                f"({gain_pct:.2f}%) | selling {sell_fraction * 100:.0f}% WMATIC"
            )
        else:
            amount_in = int(wmatic_balance * sell_fraction * 1e18)
            print(f"🛡️ PROTECTION TRIGGERED: {reason} — Force selling")
    else:
        current_price = get_live_wmatic_price()
        should_take_profit, profit_signal = evaluate_take_profit(current_price, state)
        save_state(state)
        if should_take_profit and wmatic_balance > 0:
            sell_fraction = min(1.0, max(0.1, float(profit_signal["sell_fraction"])))
            direction = "WMATIC_TO_USDT"
            amount_in = int(wmatic_balance * sell_fraction * 1e18)
            print(
                f"💰 EXIT SIGNAL: {profit_signal['reason']} | {profit_signal['message']} | "
                f"selling {sell_fraction * 100:.0f}% WMATIC"
            )
        else:
            if profit_signal and profit_signal["reason"] == "HOLD":
                print(f"📈 {profit_signal['message']}")
        # === 80/20 Decision ===
        if not direction:
            if os.getenv("COPY_TRADING_ENABLED", "true").lower() == "true" and get_target_wallets():
                print("🔄 REAL POLYCOPY MODE (20%) - Monitoring live wallets")
                # === v2.6 Per-wallet cooldown check ===
                wallets = get_target_wallets()
                active_wallets = [w for w in wallets if can_trade_wallet(w)]
                if not active_wallets:
                    print(f"⏳ All wallets in {PER_WALLET_COOLDOWN}s cooldown — waiting 30s...")
                    time.sleep(30)
                    return
                direction = "USDT_TO_WMATIC"
                trade_size = max(8.0, min(18.0, usdt_balance * COPY_TRADE_PCT))
                amount_in = int(trade_size * 1_000_000)
            else:
                print("🔄 MAIN STRATEGY MODE (80%)")
                trade_size = max(15.0, min(35.0, usdt_balance * 0.28))
                wmatic_value_usd = wmatic_balance * current_price

                if usdt_balance < 25:
                    direction = "WMATIC_TO_USDT"
                    amount_in = int(wmatic_balance * 0.45 * 1e18)
                    print(f"🔄 USDT RESERVE PROTECTION: ${usdt_balance:.2f} < $45")
                elif wmatic_value_usd > 52:
                    direction = "WMATIC_TO_USDT"
                    amount_in = int(wmatic_balance * 0.45 * 1e18)
                    print(f"🔄 Taking profit (WMATIC high: ${wmatic_value_usd:.2f})")
                elif wmatic_value_usd < 40 and wmatic_balance > 50:
                    direction = "WMATIC_TO_USDT"
                    amount_in = int(wmatic_balance * 0.28 * 1e18)
                    print(f"🔄 Cutting loss (WMATIC down: ${wmatic_value_usd:.2f})")
                else:
                    direction = "USDT_TO_WMATIC"
                    amount_in = int(trade_size * 1_000_000)
                    print(f"🔄 Buying WMATIC (hold preferred) | Size: ${trade_size:.2f}")

        if direction == "USDT_TO_WMATIC":
            record_buy(current_price, trade_size, "pending")

    tx_hash = await approve_and_swap(w3, os.getenv("POLYGON_PRIVATE_KEY"), amount_in, direction=direction)
    if tx_hash:
        print("✅ Swap executed successfully!")
    else:
        print("⚠️ Swap failed")

    state["last_run"] = time.time()
    save_state(state)
    print(f"✅ Cycle done — next in ~{COOLDOWN_MINUTES} min")

if __name__ == "__main__":
    asyncio.run(main())
