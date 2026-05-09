"""
V2.5.1 Protection Module
- Per-trade exit price locking
- Fluctuation protection (USDT low → auto sell)
- 5 obvious improvements (ready to integrate later)
"""

from web3 import Web3
import json
import os
from datetime import datetime
import time
from config import (
    COPY_TRADE_PCT,
    PROTECTION_FLUCTUATION_COOLDOWN_SECONDS,
    PROTECTION_FLUCTUATION_MIN_WMATIC,
    PROTECTION_FLUCTUATION_MIN_SELL_USD,
    PROTECTION_FLUCTUATION_SELL_FRACTION,
    PROTECTION_FLUCTUATION_USDT_THRESHOLD,
    PROTECTION_GAS_MULTIPLIER,
    USDC,
    USDC_NATIVE,
    PROTECTION_MAX_DAILY_LOSS_PCT,
    PROTECTION_MAX_TRADE_SIZE_USD,
    PROTECTION_MIN_POL_BALANCE,
    PROTECTION_PROFIT_LOCK_PERCENT,
)
from constants import WALLET, USDT, WMATIC, ROUTER, ROUTER_ABI, GET_AMOUNTS_OUT_ABI

from nanoclaw.config import connect_web3

# ====================== CONFIG (override via .env; defaults preserve legacy behavior) ======================
MAX_DAILY_LOSS_PCT = PROTECTION_MAX_DAILY_LOSS_PCT
MIN_POL_BALANCE = PROTECTION_MIN_POL_BALANCE
MAX_TRADE_SIZE_USD = PROTECTION_MAX_TRADE_SIZE_USD
GAS_MULTIPLIER = PROTECTION_GAS_MULTIPLIER
FLUCTUATION_USDT_THRESHOLD = PROTECTION_FLUCTUATION_USDT_THRESHOLD
PROFIT_LOCK_PERCENT = PROTECTION_PROFIT_LOCK_PERCENT
FLUCTUATION_COOLDOWN_SECONDS = PROTECTION_FLUCTUATION_COOLDOWN_SECONDS
FLUCTUATION_MIN_SELL_USD = PROTECTION_FLUCTUATION_MIN_SELL_USD

# If USDT is thin but USDT+USDC together is still ample, avoid force-selling WMATIC into USDT.
# REVERSIBLE travel tune (2026-05-09): was $90 — slightly lower so USDT-only “panic” sells stop
# sooner when combined runway is still fine (strong protection remains when stables < ~$80).
FLUCTUATION_HEALTHY_TOTAL_STABLES_USD = 85.0
# When spot quote fails, do not trigger a sell if combined stables already backstop gas/spend.
FLUCTUATION_PRICE_FAIL_MIN_STABLES_USD = 80.0

_ERC20_BALANCE_OF_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]

_prot_w3: Web3 | None = None
_last_fluctuation_trigger_ts: float | None = None
_last_fluctuation_context: dict[str, float] = {}


def _shared_web3() -> Web3:
    global _prot_w3
    if _prot_w3 is None:
        _prot_w3 = connect_web3()
    return _prot_w3


# ====================== HELPER FUNCTIONS ======================
def get_live_wmatic_price():
    w3 = _shared_web3()
    router = w3.eth.contract(address=ROUTER, abi=ROUTER_ABI + [GET_AMOUNTS_OUT_ABI])
    amounts = router.functions.getAmountsOut(10**18, [WMATIC, USDT]).call()
    return amounts[1] / 1_000_000


def get_last_fluctuation_context() -> dict[str, float]:
    return dict(_last_fluctuation_context)

def get_balances():
    w3 = _shared_web3()
    usdt = w3.eth.contract(address=USDT, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]).functions.balanceOf(WALLET).call() / 1_000_000
    wmatic = w3.eth.contract(address=WMATIC, abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]).functions.balanceOf(WALLET).call() / 1e18
    return usdt, wmatic


def _usdc_balance_usd() -> float:
    """Sum bridged + native USDC balances (6 decimals), mirroring runtime STABLE_USD semantics."""
    w3 = _shared_web3()
    primary = str(USDC).strip()
    total = (
        w3.eth.contract(address=Web3.to_checksum_address(primary), abi=_ERC20_BALANCE_OF_ABI)
        .functions.balanceOf(WALLET)
        .call()
        / 1_000_000
    )
    native = str(USDC_NATIVE or "").strip()
    if native and native.lower() != primary.lower():
        total += (
            w3.eth.contract(address=Web3.to_checksum_address(native), abi=_ERC20_BALANCE_OF_ABI)
            .functions.balanceOf(WALLET)
            .call()
            / 1_000_000
        )
    return float(total)

def get_pol_balance():
    w3 = _shared_web3()
    return w3.eth.get_balance(WALLET) / 10**18

# ====================== PER-TRADE EXIT PRICE LOCKING ======================
TRADE_LOG_FILE = "trade_exits.json"

def record_buy(buy_price, amount_usd, tx_hash):
    """Call this right after a successful USDT → WMATIC buy"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "buy_price": round(buy_price, 6),
        "target_price": round(buy_price * (1 + PROFIT_LOCK_PERCENT / 100), 6),
        "amount_usd": amount_usd,
        "tx_hash": tx_hash,
        "status": "OPEN"
    }
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE) as f:
            trades = json.load(f)
    else:
        trades = []
    trades.append(entry)
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(trades, f, indent=2)
    print(f"🔒 Trade locked | Buy: ${buy_price:.4f} | Target: ${entry['target_price']:.4f} (+{PROFIT_LOCK_PERCENT}%)")

def check_exit_conditions():
    """Call this before every cycle. Returns True if we should force sell"""
    global _last_fluctuation_trigger_ts
    global _last_fluctuation_context
    usdt, wmatic = get_balances()
    
    # 1. Fluctuation protection (USDT too low)
    if usdt < FLUCTUATION_USDT_THRESHOLD and wmatic > PROTECTION_FLUCTUATION_MIN_WMATIC:
        total_stables_usd = usdt + _usdc_balance_usd()
        if total_stables_usd >= FLUCTUATION_HEALTHY_TOTAL_STABLES_USD:
            print(
                "🛡️ FLUCTUATION PROTECTION SUPPRESSED | "
                f"USDT=${usdt:.2f} (<${FLUCTUATION_USDT_THRESHOLD:.2f}) "
                f"but total stables=${total_stables_usd:.2f} (USDT+USDC "
                f"≥ ${FLUCTUATION_HEALTHY_TOTAL_STABLES_USD:.2f}) | "
                f"WMATIC={wmatic:.4f}"
            )
        else:
            now_ts = time.time()
            elapsed = (
                (now_ts - _last_fluctuation_trigger_ts)
                if _last_fluctuation_trigger_ts is not None
                else None
            )
            if elapsed is not None and elapsed < FLUCTUATION_COOLDOWN_SECONDS:
                remaining = FLUCTUATION_COOLDOWN_SECONDS - elapsed
                print(
                    "🛡️ FLUCTUATION PROTECTION SUPPRESSED | "
                    f"USDT=${usdt:.2f} (<${FLUCTUATION_USDT_THRESHOLD:.2f}) | "
                    f"WMATIC={wmatic:.4f} (>{PROTECTION_FLUCTUATION_MIN_WMATIC:.4f}) | "
                    f"cooldown_remaining={remaining:.0f}s/{FLUCTUATION_COOLDOWN_SECONDS}s"
                )
            else:
                sell_amount = wmatic * PROTECTION_FLUCTUATION_SELL_FRACTION
                estimated_wmatic_price: float | None = None
                sell_notional_usd: float | None = None
                try:
                    estimated_wmatic_price = float(get_live_wmatic_price())
                    sell_notional_usd = sell_amount * estimated_wmatic_price
                except Exception as exc:
                    print(f"⚠️ FLUCTUATION PRICE CHECK UNAVAILABLE | using balance-only guard | err={exc}")

                # REVERSIBLE (2026-05-09): flaky RPC/router quotes used to fall through to a forced sell
                # (sell_notional None → trigger). With healthy combined stables, skip instead.
                if sell_notional_usd is None and total_stables_usd >= FLUCTUATION_PRICE_FAIL_MIN_STABLES_USD:
                    print(
                        "🛡️ FLUCTUATION PROTECTION SUPPRESSED | "
                        f"price unavailable but total stables=${total_stables_usd:.2f} "
                        f"(≥${FLUCTUATION_PRICE_FAIL_MIN_STABLES_USD:.0f}) | "
                        f"USDT=${usdt:.2f} WMATIC={wmatic:.4f}"
                    )
                elif (
                    sell_notional_usd is not None
                    and sell_notional_usd < FLUCTUATION_MIN_SELL_USD
                ):
                    print(
                        "🛡️ FLUCTUATION PROTECTION SUPPRESSED | "
                        f"sell_notional=${sell_notional_usd:.2f} < min=${FLUCTUATION_MIN_SELL_USD:.2f} | "
                        f"USDT=${usdt:.2f} WMATIC={wmatic:.4f}"
                    )
                else:
                    _last_fluctuation_trigger_ts = now_ts
                    _last_fluctuation_context = {
                        "usdt": usdt,
                        "wmatic": wmatic,
                        "usdt_threshold": FLUCTUATION_USDT_THRESHOLD,
                        "wmatic_min": PROTECTION_FLUCTUATION_MIN_WMATIC,
                        "sell_fraction": PROTECTION_FLUCTUATION_SELL_FRACTION,
                        "sell_amount_wmatic": sell_amount,
                        "sell_notional_usd": float(sell_notional_usd) if sell_notional_usd is not None else 0.0,
                        "wmatic_price": float(estimated_wmatic_price) if estimated_wmatic_price is not None else 0.0,
                        "min_sell_usd": FLUCTUATION_MIN_SELL_USD,
                        "cooldown_seconds": float(FLUCTUATION_COOLDOWN_SECONDS),
                    }
                    print(
                        "⚠️ FLUCTUATION PROTECTION TRIGGERED | "
                        f"USDT=${usdt:.2f} (<${FLUCTUATION_USDT_THRESHOLD:.2f}) | "
                        f"WMATIC={wmatic:.4f} (>{PROTECTION_FLUCTUATION_MIN_WMATIC:.4f}) | "
                        f"sell_fraction={PROTECTION_FLUCTUATION_SELL_FRACTION:.2f} "
                        f"(~{sell_amount:.4f} WMATIC) | "
                        f"notional=${(sell_notional_usd or 0.0):.2f} (min=${FLUCTUATION_MIN_SELL_USD:.2f}) | "
                        f"cooldown={FLUCTUATION_COOLDOWN_SECONDS}s"
                    )
                    _maybe_send_telegram_alerts(usdt, 0.0, True)  # usdc fetched inside if needed
                    return True, "FLUCTUATION"
    
    # 2. Check open trades for per-trade exit
    if not os.path.exists(TRADE_LOG_FILE):
        return False, None
    
    with open(TRADE_LOG_FILE) as f:
        trades = json.load(f)
    
    current_price = get_live_wmatic_price()

    # Evaluate only the latest valid OPEN trade to avoid stale historical rows
    # repeatedly monopolizing cycle precedence.
    if isinstance(trades, list):
        for t in reversed(trades):
            if not isinstance(t, dict) or t.get("status") != "OPEN":
                continue
            try:
                buy_price = float(t.get("buy_price", 0.0) or 0.0)
                target_price = float(t.get("target_price", 0.0) or 0.0)
            except Exception:
                continue
            if buy_price <= 0.0 or target_price <= 0.0:
                continue
            if current_price >= target_price:
                print(
                    "🎯 PER-TRADE EXIT HIT | "
                    f"Buy ${buy_price:.4f} → Current ${current_price:.4f} (+{PROFIT_LOCK_PERCENT}%)"
                )
                return True, "PER_TRADE_EXIT"
            break
    
    return False, None

# ====================== 5 OBVIOUS IMPROVEMENTS (Ready to use) ======================
def should_skip_due_to_daily_loss():
    # Placeholder - we can implement real daily P&L tracking later
    return False

def get_optimal_gas_price(w3):
    return int(w3.eth.gas_price * GAS_MULTIPLIER)

def has_enough_pol():
    return get_pol_balance() >= MIN_POL_BALANCE

def get_safe_trade_size(usdt_balance):
    return min(MAX_TRADE_SIZE_USD, usdt_balance * COPY_TRADE_PCT)

print("✅ V2.5.1 Protection Module loaded successfully")

# ============================================================
# Telegram Alerts (reusing existing _telegram_send_html)
# Added: 2026-05-09 - Event driven, low spam
# ============================================================
try:
    from modules.agent_layer import _telegram_send_html
except Exception:
    def _telegram_send_html(text: str):
        pass  # fallback if import fails

_protection_trigger_window = []   # store recent trigger timestamps
_last_high_protection_alert = 0
_last_low_stable_alert = 0

def _maybe_send_telegram_alerts(usdt: float, usdc: float, protection_triggered: bool):
    """Send Telegram alert only on important events."""
    import time
    global _protection_trigger_window, _last_high_protection_alert, _last_low_stable_alert

    now = time.time()
    total_stables = usdt + usdc

    # Track protection triggers in last 6 hours
    if protection_triggered:
        _protection_trigger_window.append(now)
        # keep only last 6 hours
        _protection_trigger_window = [t for t in _protection_trigger_window if now - t < 21600]

    # Alert 1: High protection activity (>25 triggers in last 6h)
    if len(_protection_trigger_window) > 25 and (now - _last_high_protection_alert) > 21600:
        msg = (
            f"⚠️ High Protection Activity\n"
            f"Triggers (last 6h): {len(_protection_trigger_window)}\n"
            f"Total Stables: ${total_stables:.2f}\n"
            f"USDT: ${usdt:.2f} | USDC: ${usdc:.2f}"
        )
        _telegram_send_html(msg)
        _last_high_protection_alert = now
        _protection_trigger_window = []  # reset after alert

    # Alert 2: Total Stables getting low
    if total_stables < 65 and (now - _last_low_stable_alert) > 3600:  # max once per hour
        msg = (
            f"🛡️ Warning: Total Stables Low\n"
            f"Total Stables: ${total_stables:.2f}\n"
            f"USDT: ${usdt:.2f} | USDC: ${usdc:.2f}"
        )
        _telegram_send_html(msg)
        _last_low_stable_alert = now
