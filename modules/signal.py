"""X-Signal equity eligibility, auto-USDC, planning, evaluation helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional, Sequence

import config as cfg
from config import CHAIN_HINT_WRONG_ETH_ADDRESSES, X_SIGNAL_STRONG_THRESHOLD
from nanoclaw.strategies.signal_equity_trader import (
    EquityBuildPlanParams,
    EquityTradePlan,
    FollowedEquity,
    SignalEquityTrader,
    SignalEquityTraderConfig,
)

from . import runtime
from .runtime import (
    AUTO_POPULATE_USDC_AMOUNT,
    Balances,
    MAX_GWEI,
    TradeDecision,
    USDC,
    X_SIGNAL_AUTO_USDC_TARGET,
    X_SIGNAL_AUTO_USDC_MIN_SWAP_USD,
    X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS,
    X_SIGNAL_AUTO_USDC_TOPUP_ENABLED,
    X_SIGNAL_EQUITY_TRADER,
    X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD,
    X_SIGNAL_FORCE_HIGH_CONVICTION,
    X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
    X_SIGNAL_USDC_MIN,
    X_SIGNAL_USDC_SAFE_FLOOR,
    X_SIGNAL_WMATIC_MIN_VALUE,
    approve_and_swap,
    w3,
)

logger = logging.getLogger(__name__)
_AUTO_USDC_FAILURE_STATE = {
    "next_retry_ts": 0.0,
    "last_failure_usdc": -1.0,
    "consecutive_failures": 0,
}


def _x_signal_buy_risk_level(*, usdt: float, wmatic: float) -> str:
    """
    Minimal risk classifier used to protect session PnL by scaling X-Signal BUY sizing.

    Logic (mirrors nanoreconcile operator heuristic):
    - HIGH: USDT < (PROTECTION_FLUCTUATION_USDT_THRESHOLD + 3)
    - MEDIUM: USDT < (PROTECTION_FLUCTUATION_USDT_THRESHOLD + 9) AND WMATIC > PROTECTION_FLUCTUATION_MIN_WMATIC
    - LOW: otherwise
    """
    th_usdt = float(getattr(cfg, "PROTECTION_FLUCTUATION_USDT_THRESHOLD", 0.0))
    th_wmatic = float(getattr(cfg, "PROTECTION_FLUCTUATION_MIN_WMATIC", 0.0))
    # Keep this focused on USDT + WMATIC (current damage area) with operator-intuitive constants.
    high_usdt_buffer = 3.0
    medium_usdt_buffer = 9.0
    usdt_f = float(usdt)
    wmatic_f = float(wmatic)

    if usdt_f < (th_usdt + high_usdt_buffer):
        return "HIGH"
    if usdt_f < (th_usdt + medium_usdt_buffer) and wmatic_f > th_wmatic:
        return "MEDIUM"
    return "LOW"


def _format_money(x: float) -> str:
    try:
        return f"${float(x):.2f}"
    except Exception:
        return f"{x!r}"


def _assess_x_signal_buy_risk(
    *,
    onchain_usdt: float,
    onchain_wmatic: float,
    snapshot_usdt: Optional[float] = None,
) -> tuple[str, dict[str, object]]:
    """
    Risk assessment used to protect Session PnL.

    In addition to the threshold rules, this supports an explicit HIGH-risk trigger on
    "very large USDT divergence" between a caller-provided snapshot and fresh on-chain USDT.
    """
    th_usdt = float(getattr(cfg, "PROTECTION_FLUCTUATION_USDT_THRESHOLD", 0.0))
    th_wmatic = float(getattr(cfg, "PROTECTION_FLUCTUATION_MIN_WMATIC", 0.0))
    high_usdt_buffer = 3.0
    medium_usdt_buffer = 9.0
    high_usdt_divergence_usd = float(cfg.env_float("X_SIGNAL_BUY_RISK_HIGH_USDT_DIVERGENCE_USD", 20.0))

    usdt_f = float(onchain_usdt)
    wmatic_f = float(onchain_wmatic)
    divergence = None
    divergence_trigger = False
    if snapshot_usdt is not None:
        try:
            divergence = abs(float(snapshot_usdt) - usdt_f)
            divergence_trigger = divergence >= high_usdt_divergence_usd
        except Exception:
            divergence = None
            divergence_trigger = False

    reasons: list[str] = []
    if usdt_f < (th_usdt + high_usdt_buffer):
        reasons.append("usdt_below_high_buffer")
    if divergence_trigger:
        reasons.append("very_large_usdt_divergence")

    if reasons:
        level = "HIGH"
    elif usdt_f < (th_usdt + medium_usdt_buffer) and wmatic_f > th_wmatic:
        level = "MEDIUM"
        reasons.append("usdt_below_medium_buffer_and_wmatic_high")
    else:
        level = "LOW"
        reasons.append("no_risk_conditions_met")

    ctx: dict[str, object] = {
        "onchain_usdt": usdt_f,
        "onchain_wmatic": wmatic_f,
        "usdt_th": th_usdt,
        "wmatic_th": th_wmatic,
        "high_usdt_buffer": high_usdt_buffer,
        "medium_usdt_buffer": medium_usdt_buffer,
        "snapshot_usdt": float(snapshot_usdt) if snapshot_usdt is not None else None,
        "usdt_divergence": float(divergence) if divergence is not None else None,
        "high_usdt_divergence_usd": high_usdt_divergence_usd,
        "reasons": reasons,
    }
    return level, ctx


def _reconcile_total_portfolio_usd_with_onchain_usdc(
    total_portfolio_usd: float,
    snapshot_usdc: float,
    onchain_preferred_usdc: float,
) -> float:
    """Reconcile aggregate total with latest USDC component while keeping totals non-negative."""
    current_total = float(total_portfolio_usd)
    return max(0.0, current_total - float(snapshot_usdc) + float(onchain_preferred_usdc))


def _wrong_chain_eth_like_addresses() -> frozenset[str]:
    """Optional env CHAIN_HINT_WRONG_ETH_ADDRESSES=comma-separated; else defaults (Ethereum-mainnet-style tokens)."""
    raw = CHAIN_HINT_WRONG_ETH_ADDRESSES
    if raw:
        return frozenset(x.strip().lower() for x in raw.split(",") if x.strip())
    return frozenset(
        (
            "0xb812837b81a3a6b81d7cd74cfb19a7f2784555e5",
            "0xba47214edd2bb43099611b208f75e4b42fdcfedc",
            "0x2d1f7226bd1f780af6b9a49dcc0ae00e8df4bdee",
        )
    )


_CHAIN_HINT_ETH_LIKE = _wrong_chain_eth_like_addresses()


def _invoke_equity_build_plan(
    trader: SignalEquityTrader,
    params: EquityBuildPlanParams,
) -> tuple[Optional[EquityTradePlan], Optional[str]]:
    """Prefer ``build_plan_from_params``; fall back to kwargs for test doubles that only stub ``build_plan_with_block_reason``."""
    direct = getattr(trader, "build_plan_from_params", None)
    if callable(direct):
        return direct(params)
    return trader.build_plan_with_block_reason(
        symbol=params.symbol,
        token_address=params.token_address,
        token_decimals=params.token_decimals,
        signal_strength=params.signal_strength,
        earnings_proximity_days=params.earnings_proximity_days,
        current_price_usd=params.current_price_usd,
        usdc_balance=params.usdc_balance,
        equity_balance=params.equity_balance,
        usdt_balance=params.usdt_balance,
        wallet_address_for_gas=params.wallet_address_for_gas,
        can_trade_asset=params.can_trade_asset,
        now=params.now,
        urgent_gas=params.urgent_gas,
        allow_high_gas_override=params.allow_high_gas_override,
        upside_pct=params.upside_pct,
    )


def _cs_mod():
    import importlib

    return importlib.import_module("clean_swap")


def _load_followed_equities_json_dict() -> dict:
    path = _cs_mod().FOLLOWED_EQUITIES_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _effective_equity_signal_min(cfg: dict) -> float:
    cs = _cs_mod()
    floor = cs.X_SIGNAL_EQUITY_MIN_STRENGTH
    json_floor = float(cfg.get("min_signal_strength", floor) or floor)
    return max(json_floor, floor)


def _effective_floor_for_equity(asset: FollowedEquity, min_strength: float) -> float:
    asset_floor_raw = getattr(asset, "min_signal_strength", None)
    return float(min_strength) if asset_floor_raw is None else float(asset_floor_raw)



def _sorted_and_eligible_equities(
    assets_seq: Sequence[FollowedEquity],
    min_strength: float,
    strong_threshold: float,
    force_high_conviction: bool = True,
    high_conviction_threshold: float = 0.80,
    force_eligible_threshold: float = 0.80,
) -> tuple[list[FollowedEquity], list[FollowedEquity]]:
    """
    Filter followed equities by eligibility criteria.

    An asset is eligible if ANY of:
    1. abs(signal) >= force_eligible_threshold (bypasses JSON/asset floors for rotation into major names)
    2. signal >= strong_threshold (normal strong signal)
    3. signal >= asset_floor (asset has own floor override)

    ``force_high_conviction`` / ``high_conviction_threshold`` are kept for logging and gas override only.

    Returns (all_sorted_by_strength, eligible_only)
    """
    assets_list = sorted(
        assets_seq,
        key=lambda a: abs(float(a.signal_strength)),
        reverse=True,
    )
    eligible: list[FollowedEquity] = []
    
    print(f"{runtime._nanolog()}=== ELIGIBILITY CHECK START ===")
    print(
        f"{runtime._nanolog()}  min_strength={min_strength:.3f} | strong_threshold={strong_threshold:.3f} | "
        f"force_eligible_threshold={force_eligible_threshold:.3f} | "
        f"high_conviction_threshold={high_conviction_threshold:.3f} | force_high_conviction={force_high_conviction}"
    )
    
    for a in assets_list:
        effective_floor = _effective_floor_for_equity(a, min_strength)
        strength = abs(float(a.signal_strength))
        
        force_eligible_bypass = strength >= float(force_eligible_threshold)
        eligible_by_strong = strength >= float(strong_threshold)
        eligible_by_floor = strength >= float(effective_floor)
        
        is_eligible = force_eligible_bypass or eligible_by_strong or eligible_by_floor
        
        if is_eligible:
            eligible.append(a)
            reason_parts = []
            if force_eligible_bypass:
                reason_parts.append(f"force_eligible (>={force_eligible_threshold:.3f})")
            if eligible_by_strong:
                reason_parts.append(f"strong_threshold ({strong_threshold:.3f}+)")
            if eligible_by_floor:
                reason_parts.append(f"asset_floor ({effective_floor:.3f}+)")
            reason = " | ".join(reason_parts)
            print(
                f"{runtime._nanolog()}  ✅ ELIGIBLE | {a.symbol:12s} | signal={strength:6.3f} | "
                f"by: {reason}"
            )
        else:
            print(
                f"{runtime._nanolog()}  ❌ FILTERED | {a.symbol:12s} | signal={strength:6.3f} | "
                f"raw_floor={a.min_signal_strength!r} | effective_floor={effective_floor:.3f} | "
                f"strong_threshold={strong_threshold:.3f} | "
                f"force_eligible_threshold={force_eligible_threshold:.3f}"
            )
    
    print(f"{runtime._nanolog()}=== ELIGIBILITY CHECK END: {len(eligible)}/{len(assets_list)} eligible ===\n")
    return assets_list, eligible


def _order_eligible_x_signal_candidates(
    eligible: Sequence[FollowedEquity],
    *,
    per_asset_cooldown_seconds: int,
) -> list[FollowedEquity]:
    cs = _cs_mod()
    seq = list(eligible)
    if not cs.X_SIGNAL_EQUITY_COOLDOWN_FIRST_SORT:
        return sorted(seq, key=lambda a: -abs(float(a.signal_strength)))

    def sort_key(a: FollowedEquity) -> tuple[int, float]:
        sym = str(a.symbol).strip()
        cooldown_ok = cs.can_trade_asset(sym, None, int(per_asset_cooldown_seconds))
        return (0 if cooldown_ok else 1, -abs(float(a.signal_strength)))

    return sorted(seq, key=sort_key)


def _facade_strong_buy_present() -> bool:
    return _cs_mod()._strong_x_signal_buy_present()


def strong_buy_detector() -> bool:
    """True if followed_equities has a BUY with strength ≥ X_SIGNAL_STRONG_THRESHOLD (same bar as equity trades)."""
    cs = _cs_mod()
    cfg = cs._load_followed_equities_json_dict()
    if not bool(cfg.get("enabled", True)):
        return False
    min_strength = cs._effective_equity_signal_min(cfg)
    strong_thr = cs.X_SIGNAL_STRONG_THRESHOLD
    fe_thr = cs.X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD
    assets_seq = cs.X_SIGNAL_EQUITY_TRADER.load_followed_equities()
    _, eligible = _sorted_and_eligible_equities(
        assets_seq,
        min_strength,
        strong_thr,
        force_high_conviction=X_SIGNAL_FORCE_HIGH_CONVICTION,
        high_conviction_threshold=X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
        force_eligible_threshold=fe_thr,
    )
    return any(
        float(a.signal_strength) > 0 and float(a.signal_strength) >= strong_thr for a in eligible
    )


def ensure_usdc_for_x_signal(min_usdc: float = 8.0, min_wmatic_value: float = 15.0, force: bool = False) -> bool:
    """If USDC is below ``min_usdc`` and (a strong X-Signal BUY is active or force=True), swap USDT→USDC first, then WMATIC→USDC."""
    fac = _cs_mod()
    balances = fac.get_balances()
    print(
        f"{runtime._nanolog()}AUTO-USDC consider | force={bool(force)} | "
        f"usdc=${balances.usdc:.2f} usdt=${balances.usdt:.2f} wmatic={balances.wmatic:.6f} "
        f"min_usdc=${float(min_usdc):.2f} min_wmatic_value=${float(min_wmatic_value):.2f}"
    )
    if not bool(getattr(fac, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", X_SIGNAL_AUTO_USDC_TOPUP_ENABLED)):
        print(f"{runtime._nanolog()}AUTO-USDC skipped — disabled by X_SIGNAL_AUTO_USDC_TOPUP_ENABLED")
        return False
    if balances.usdc >= min_usdc:
        print(
            f"{runtime._nanolog()}AUTO-USDC skipped — already funded "
            f"(usdc=${balances.usdc:.2f} >= min_usdc=${float(min_usdc):.2f})"
        )
        return True
    if not force and not _facade_strong_buy_present():
        print(
            f"{runtime._nanolog()}AUTO-USDC skipped — no strong BUY signal "
            "(force=False and strong-buy detector is false)"
        )
        return False

    gst = fac.GAS_PROTECTOR.get_safe_status(
        address=fac.WALLET, urgent=False, min_pol=fac.MIN_POL_FOR_GAS
    )
    if not gst.get("ok", False):
        print(
            f"{runtime._nanolog()}AUTO-USDC skipped — gas/POL guard "
            f"(gas_ok={gst.get('gas_ok')}, pol={gst.get('pol_balance')}, min_pol={fac.MIN_POL_FOR_GAS})"
        )
        return False

    key, _key_source = cfg.resolve_private_key(log_success=True)
    if not key:
        print(f"{runtime._nanolog()}AUTO-USDC skipped — no private key")
        return False

    min_swap_usd = max(1.0, float(getattr(fac, "X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", X_SIGNAL_AUTO_USDC_MIN_SWAP_USD)))
    target_usdc = max(float(min_usdc), float(getattr(fac, "X_SIGNAL_AUTO_USDC_TARGET", X_SIGNAL_AUTO_USDC_TARGET)))
    pre_usdc = float(balances.usdc)
    attempted_legs: list[str] = []
    fail_class = "no_leg_attempted"

    def _target_swap_usd(current_usdc: float) -> float:
        shortfall = max(0.0, target_usdc - float(current_usdc))
        return max(shortfall * 1.05, float(AUTO_POPULATE_USDC_AMOUNT), min_swap_usd)

    async def _swap_wmatic(amount_wei: int) -> bool:
        if amount_wei <= 0:
            return False
        h = await approve_and_swap(
            w3,
            key,
            amount_wei,
            direction="WMATIC_TO_USDC",
        )
        return h is not None

    async def _swap_usdt(amount_units: int) -> bool:
        if amount_units <= 0:
            return False
        h = await approve_and_swap(
            w3,
            key,
            amount_units,
            direction="USDT_TO_USDC",
        )
        return h is not None

    def _run(coro):
        try:
            return asyncio.run(coro)
        except Exception as exc:
            nonlocal fail_class
            fail_class = "swap_exception"
            print(
                f"{runtime._nanolog()}AUTO-USDC swap call raised exception; "
                f"submission status unknown — {exc}"
            )
            return False

    # Preferred source: USDT first.
    current = fac.get_balances()
    print(
        f"{runtime._nanolog()}AUTO-USDC consider | source=USDT-first | "
        f"usdc=${current.usdc:.2f} usdt=${current.usdt:.2f} wmatic={current.wmatic:.6f} "
        f"target=${target_usdc:.2f} min_swap=${min_swap_usd:.2f}"
    )
    if current.usdt >= min_swap_usd:
        usdt_amt = min(current.usdt * 0.95, _target_swap_usd(current.usdc))
        if usdt_amt >= min_swap_usd:
            attempted_legs.append("USDT_TO_USDC")
            print(f"{runtime._nanolog()}Auto top-up triggered: swapping ${usdt_amt:.2f} from USDT → USDC")
            usdt_ok = _run(_swap_usdt(int(usdt_amt * 1_000_000)))
            post_usdt = fac.get_balances()
            print(
                f"{runtime._nanolog()}AUTO-USDC result | leg=USDT_TO_USDC | ok={usdt_ok} "
                f"| pre_usdc=${pre_usdc:.2f} | usdc_after=${post_usdt.usdc:.2f} "
                f"| target=${target_usdc:.2f}"
            )
            if usdt_ok and post_usdt.usdc >= min_usdc:
                print(
                    f"{runtime._nanolog()}AUTO-USDC final | ok=True | fail_class=none "
                    f"| legs={','.join(attempted_legs)} | pre_usdc=${pre_usdc:.2f} "
                    f"| post_usdc=${post_usdt.usdc:.2f} | target=${target_usdc:.2f}"
                )
                return True
            if not usdt_ok:
                fail_class = "usdt_swap_failed"
            else:
                fail_class = "usdt_leg_insufficient"

    # Fallback source: WMATIC when USDT is insufficient or first leg didn't reach floor.
    after_usdt = fac.get_balances()
    try:
        wmatic_price = float(fac.get_live_wmatic_price())
    except Exception:
        wmatic_price = 0.0
    if wmatic_price <= 0:
        print(f"{runtime._nanolog()}AUTO-USDC skipped — WMATIC price unavailable for fallback leg")
        fail_class = "wmatic_price_unavailable"
        return after_usdt.usdc >= min_usdc
    if (after_usdt.wmatic * wmatic_price) < max(float(min_wmatic_value), min_swap_usd):
        fail_class = "wmatic_leg_below_min_value"
        return after_usdt.usdc >= min_usdc

    wmatic_swap_usd = min(after_usdt.wmatic * wmatic_price * 0.95, _target_swap_usd(after_usdt.usdc))
    if wmatic_swap_usd < min_swap_usd:
        fail_class = "wmatic_swap_below_min_swap_usd"
        return after_usdt.usdc >= min_usdc
    wmatic_to_swap = min(after_usdt.wmatic * 0.95, wmatic_swap_usd / wmatic_price)
    amount_wei = int(wmatic_to_swap * 1e18)
    if amount_wei <= 0:
        fail_class = "wmatic_amount_too_small"
        return after_usdt.usdc >= min_usdc
    attempted_legs.append("WMATIC_TO_USDC")
    print(f"{runtime._nanolog()}Auto top-up triggered: swapping ${wmatic_swap_usd:.2f} from WMATIC → USDC")
    ok = _run(_swap_wmatic(amount_wei))
    post_wmatic = fac.get_balances()
    print(
        f"{runtime._nanolog()}AUTO-USDC result | leg=WMATIC_TO_USDC | ok={ok} "
        f"| pre_usdc=${pre_usdc:.2f} | usdc_after=${post_wmatic.usdc:.2f} "
        f"| target=${target_usdc:.2f}"
    )
    topup_ok = bool(ok and post_wmatic.usdc >= min_usdc)
    if not topup_ok:
        if not ok:
            fail_class = "wmatic_swap_failed"
        else:
            fail_class = "wmatic_leg_insufficient"
    print(
        f"{runtime._nanolog()}AUTO-USDC final | ok={topup_ok} | fail_class={fail_class if not topup_ok else 'none'} "
        f"| legs={','.join(attempted_legs) if attempted_legs else 'none'} | pre_usdc=${pre_usdc:.2f} "
        f"| post_usdc=${post_wmatic.usdc:.2f} | target=${target_usdc:.2f}"
    )
    return topup_ok


def _project_balances_after_auto_usdc(
    balances: Balances,
    *,
    min_usdc: float,
    min_wmatic_value: float,
) -> Balances:
    """Mirror ``ensure_usdc_for_x_signal`` guards and sizing without swaps (dry-run fair USDC for equity plans)."""
    def _projected_balances(*, usdt: float, wmatic: float, pol: float, usdc: float) -> Balances:
        return Balances(
            usdt=usdt,
            wmatic=wmatic,
            pol=pol,
            usdc=usdc,
            followed_equity_usd=balances.followed_equity_usd,
            total_portfolio_usd=balances.total_portfolio_usd,
        )

    if balances.usdc >= min_usdc:
        print(
            f"{runtime._nanolog()}AUTO-USDC project_balances skipped — already funded "
            f"(usdc=${balances.usdc:.2f} >= min_usdc=${float(min_usdc):.2f})"
        )
        return balances
    if not _facade_strong_buy_present():
        print(f"{runtime._nanolog()}AUTO-USDC project_balances skipped — no strong BUY signal")
        return balances

    fac = _cs_mod()
    gst = fac.GAS_PROTECTOR.get_safe_status(
        address=fac.WALLET, urgent=False, min_pol=fac.MIN_POL_FOR_GAS
    )
    if not gst.get("ok", False):
        print(f"{runtime._nanolog()}AUTO-USDC project_balances skipped — gas/POL guard")
        return balances

    key, _key_source = cfg.resolve_private_key(log_success=True)
    if not key:
        print(f"{runtime._nanolog()}AUTO-USDC project_balances skipped — no private key")
        return balances

    try:
        wmatic_price = float(fac.get_live_wmatic_price())
    except Exception:
        print(f"{runtime._nanolog()}AUTO-USDC project_balances skipped — WMATIC price unavailable")
        return balances
    if wmatic_price <= 0:
        print(f"{runtime._nanolog()}AUTO-USDC project_balances skipped — WMATIC price non-positive")
        return balances

    shortfall = max(0.0, float(min_usdc) - float(balances.usdc))
    min_swap_usd = max(1.0, float(getattr(fac, "X_SIGNAL_AUTO_USDC_MIN_SWAP_USD", X_SIGNAL_AUTO_USDC_MIN_SWAP_USD)))
    target_usd = max(shortfall * 1.05, float(AUTO_POPULATE_USDC_AMOUNT), min_swap_usd)
    wmatic_usd = balances.wmatic * wmatic_price

    if balances.usdt >= min_swap_usd:
        usdt_amt = min(balances.usdt * 0.95, target_usd)
        if usdt_amt >= min_swap_usd and balances.usdc + usdt_amt >= min_usdc:
            print(
                f"{runtime._nanolog()}AUTO-USDC project_balances | path=USDT_TO_USDC "
                f"| projected_usdc=${balances.usdc + usdt_amt:.2f}"
            )
            return _projected_balances(
                usdt=balances.usdt - usdt_amt,
                wmatic=balances.wmatic,
                pol=balances.pol,
                usdc=balances.usdc + usdt_amt,
            )

    if wmatic_usd >= max(float(min_wmatic_value), min_swap_usd):
        swap_usd = min(wmatic_usd * 0.95, target_usd)
        if swap_usd >= min_swap_usd:
            wmatic_to_swap = min(balances.wmatic * 0.95, swap_usd / wmatic_price)
            if wmatic_to_swap > 0:
                est_usdc_out = min(wmatic_to_swap * wmatic_price, swap_usd)
                if balances.usdc + est_usdc_out >= min_usdc:
                    print(
                        f"{runtime._nanolog()}AUTO-USDC project_balances | path=WMATIC_TO_USDC "
                        f"| projected_usdc=${balances.usdc + est_usdc_out:.2f}"
                    )
                    return _projected_balances(
                        usdt=balances.usdt,
                        wmatic=balances.wmatic - wmatic_to_swap,
                        pol=balances.pol,
                        usdc=balances.usdc + est_usdc_out,
                    )
    return balances


def _tuned_signal_equity_trader(min_signal_strength: float) -> SignalEquityTrader:
    """Build a trader with tuned enablement; `min_signal_strength` kept for API compatibility (eligibility-only)."""
    _ = min_signal_strength
    cs = _cs_mod()
    root = cs.X_SIGNAL_EQUITY_TRADER
    base_cfg = getattr(root, "config", None)
    gp = getattr(root, "gas_protector", cs.GAS_PROTECTOR)
    usdc_a = getattr(root, "usdc_address", USDC)
    strong_thr = float(getattr(base_cfg, "strong_signal_threshold", X_SIGNAL_STRONG_THRESHOLD))
    fe_thr = float(getattr(base_cfg, "force_eligible_threshold", cs.X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD))
    if base_cfg is None:
        tuned_cfg = SignalEquityTraderConfig(
            enabled=True,
            strong_signal_threshold=strong_thr,
            force_eligible_threshold=fe_thr,
        )
    else:
        tuned_cfg = SignalEquityTraderConfig(
            **{
                **base_cfg.__dict__,
                "enabled": True,
                "strong_signal_threshold": strong_thr,
                "force_eligible_threshold": fe_thr,
            }
        )
    return SignalEquityTrader(config=tuned_cfg, gas_protector=gp, usdc_address=usdc_a)



def try_x_signal_equity_decision(balances: Balances, *, dry_run: bool = False) -> Optional[TradeDecision]:
    """Highest-priority iteration: eligible assets × SignalEquityTrader.build_plan; first plan wins."""
    decision: Optional[TradeDecision] = None
    result: Optional[str] = None
    eligible_count = 0
    fcb = _cs_mod()

    def _polygon_chain_hint(sym: str, token_address: str) -> Optional[str]:
        t = (token_address or "").strip().lower()
        if t in _CHAIN_HINT_ETH_LIKE:
            return f"{sym}: token may be wrong chain (not Polygon)"
        return None

    if not fcb.ENABLE_X_SIGNAL_EQUITY:
        print(
            f"X-SIGNAL EQUITY SUMMARY | Assets checked: {eligible_count} | USDC: ${balances.usdc:.2f} | "
            f"Result: {'NO_TRADE_ENABLE_X_SIGNAL_EQUITY_FALSE'}"
        )
        return None

    snapshot_usdt = float(balances.usdt)
    if not dry_run:
        balances = fcb.get_balances()

    risk_level, risk_ctx = _assess_x_signal_buy_risk(
        onchain_usdt=float(balances.usdt),
        onchain_wmatic=float(balances.wmatic),
        snapshot_usdt=(None if dry_run else snapshot_usdt),
    )
    buy_mult = 1.0
    skip_buys = False

    if risk_level == "HIGH":
        buy_mult = 0.0
        skip_buys = True

    elif risk_level == "MEDIUM":
        risk_reasons = set(str(x) for x in (risk_ctx.get("reasons") or []))
        medium_usdt_wmatic_guard = "usdt_below_medium_buffer_and_wmatic_high" in risk_reasons

        if medium_usdt_wmatic_guard and sym in ("WMATIC", "WMATIC_ALPHA"):
            # Strict defense only for WMATIC
            print(f"{runtime._nanolog()}X-SIGNAL BUY SKIPPED | symbol={sym} | risk=MEDIUM | reason=usdt_below_medium_buffer_and_wmatic_high")
            continue
        # For WETH_ALPHA, WBTC_ALPHA, LINK_ALPHA etc. → they continue normally even in MEDIUM

    # This print runs for everything that was not skipped above
    print(
        f"{runtime._nanolog()}X-SIGNAL BUY RISK | Risk={risk_level} | "
        f"USDT=${float(balances.usdt):.2f} | WMATIC={float(balances.wmatic):.4f} | "
        f"buy_size_multiplier={buy_mult:.2f}"
    )
    print(
        f"{runtime._nanolog()}X-SIGNAL BUY RISK CONTEXT | "
        f"usdt_th={_format_money(float(risk_ctx.get('usdt_th', 0.0)))} | "
        f"high_trigger={_format_money(float(risk_ctx.get('usdt_th', 0.0)) + float(risk_ctx.get('high_usdt_buffer', 0.0)))} | "
        f"medium_trigger={_format_money(float(risk_ctx.get('usdt_th', 0.0)) + float(risk_ctx.get('medium_usdt_buffer', 0.0)))} | "
        f"wmatic_th={float(risk_ctx.get('wmatic_th', 0.0)):.4f} | "
        f"snapshot_usdt={_format_money(float(risk_ctx.get('snapshot_usdt'))) if risk_ctx.get('snapshot_usdt') is not None else 'N/A'} | "
        f"usdt_divergence={_format_money(float(risk_ctx.get('usdt_divergence'))) if risk_ctx.get('usdt_divergence') is not None else 'N/A'} | "
        f"divergence_high={_format_money(float(risk_ctx.get('high_usdt_divergence_usd', 0.0)))} | "
        f"reasons={','.join(list(risk_ctx.get('reasons') or []))}"
    )
    if skip_buys:
        reasons = ",".join(list(risk_ctx.get("reasons") or []))
        high_trigger = float(risk_ctx.get("usdt_th", 0.0)) + float(risk_ctx.get("high_usdt_buffer", 0.0))
        medium_trigger = float(risk_ctx.get("usdt_th", 0.0)) + float(risk_ctx.get("medium_usdt_buffer", 0.0))
        usdt_div = risk_ctx.get("usdt_divergence")
        usdt_div_s = _format_money(float(usdt_div)) if usdt_div is not None else "N/A"
        div_hi = float(risk_ctx.get("high_usdt_divergence_usd", 0.0))
        print(
            f"{runtime._nanolog()}X-SIGNAL BUY DEFENSE | action={'skip_buys'} | risk={risk_level} | "
            f"reasons={reasons or 'N/A'} | "
            f"usdt={_format_money(float(risk_ctx.get('onchain_usdt', 0.0)))} "
            f"(high<{_format_money(high_trigger)}, medium<{_format_money(medium_trigger)}) | "
            f"wmatic={float(risk_ctx.get('onchain_wmatic', 0.0)):.4f} (th>{float(risk_ctx.get('wmatic_th', 0.0)):.4f}) | "
            f"usdt_div={usdt_div_s} (high>={_format_money(div_hi)})"
        )
        if risk_level == "MEDIUM":
            print(
                f"{runtime._nanolog()}Risk: MEDIUM → Pausing X-signal BUYs this cycle "
                "(early defense to protect Session PnL; USDT/WMATIC liquidity risk)"
            )
        else:
            # Keep legacy line for log matching + add stronger operator guidance.
            print(f"{runtime._nanolog()}Risk: HIGH → Skipping X-signal buy this cycle to protect PnL")
            print(
                f"{runtime._nanolog()}ACTION RECOMMENDED | Risk=HIGH | Consider top-up USDT / rebalance WMATIC→stable, "
                "or pause X-signal strategy until balances recover"
            )
        # Make it very explicit (and grep-friendly) that BUY plans will be ignored for this cycle.
        print(
            f"{runtime._nanolog()}X-SIGNAL BUY DEFENSE ACTIVE | risk={risk_level} | "
            f"buy_plans_paused=True | reasons={reasons or 'N/A'}"
        )
    elif medium_usdt_wmatic_guard:
        # Asset-specific: keep strict defense for WMATIC; allow higher-liquidity equities to proceed.
        print(
            f"{runtime._nanolog()}Risk: MEDIUM → Pausing WMATIC BUYs this cycle "
            "(early defense; USDT/WMATIC liquidity risk)"
        )

    fe_cfg = fcb._load_followed_equities_json_dict()
    cfg_enabled = bool(fe_cfg.get("enabled", True)) if isinstance(fe_cfg, dict) else True
    min_strength = fcb._effective_equity_signal_min(fe_cfg)
    tuned_trader = fcb._tuned_signal_equity_trader(min_strength)
    snapshot_usdc = float(balances.usdc)
    query_onchain = getattr(tuned_trader, "_query_onchain_usdc_balance", None)
    if callable(query_onchain):
        onchain_preferred_usdc = float(query_onchain(snapshot_usdc))
        usdc_source = str(getattr(tuned_trader, "last_usdc_balance_source", "unknown"))
    else:
        onchain_preferred_usdc = snapshot_usdc
        usdc_source = "snapshot_no_onchain_query_hook"
    balances = Balances(
        usdt=balances.usdt,
        wmatic=balances.wmatic,
        pol=balances.pol,
        usdc=onchain_preferred_usdc,
        followed_equity_usd=balances.followed_equity_usd,
        total_portfolio_usd=_reconcile_total_portfolio_usd_with_onchain_usdc(
            balances.total_portfolio_usd,
            snapshot_usdc,
            onchain_preferred_usdc,
        ),
    )
    print(
        f"{runtime._nanolog()}USDC BALANCE SOURCE | source={usdc_source} | "
        f"selected=${onchain_preferred_usdc:.2f} | snapshot=${snapshot_usdc:.2f}"
    )
    strong_thr = fcb.X_SIGNAL_STRONG_THRESHOLD
    force_eligible_thr = fcb.X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD
    force_high_conviction = fcb.X_SIGNAL_FORCE_HIGH_CONVICTION
    high_conviction_threshold = fcb.X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD
    print(
        f"{runtime._nanolog()}X-Signal eligibility floor = {min_strength:.4f}; "
        f"strong_threshold = {strong_thr:.4f}; "
        f"force_eligible_threshold = {force_eligible_thr:.4f}; "
        f"high_conviction_threshold = {high_conviction_threshold:.4f}; "
        f"force_high_conviction = {force_high_conviction}"
    )

    assets_seq = fcb.X_SIGNAL_EQUITY_TRADER.load_followed_equities()
    assets, eligible = _sorted_and_eligible_equities(
        assets_seq,
        min_strength,
        strong_thr,
        force_high_conviction=force_high_conviction,
        high_conviction_threshold=high_conviction_threshold,
        force_eligible_threshold=force_eligible_thr,
    )
    eligible_count = len(eligible)
    high_conviction = bool(cfg_enabled) and any(
        float(a.signal_strength) >= high_conviction_threshold for a in eligible if float(a.signal_strength) > 0
    )
    if high_conviction and force_high_conviction:
        print(
            f"🚀 HIGH-CONVICTION MODE ACTIVE — {high_conviction_threshold:.2f}+ signal present, "
            "force_high_conviction enabled, gas protection relaxed for this cycle"
        )
    elif high_conviction:
        print(
            f"⚠️ HIGH-CONVICTION signal present ({high_conviction_threshold:.2f}+), but force_high_conviction is disabled"
        )

    # Unified, conservative USDC top-up before planning BUY paths.
    has_buy_signal = any(float(a.signal_strength) > 0 for a in eligible)
    secs_order = int(tuned_trader.config.per_asset_cooldown_seconds)
    has_buy_ready_on_cooldown = any(
        float(a.signal_strength) > 0 and fcb.can_trade_asset(str(a.symbol).strip(), None, secs_order)
        for a in eligible
    )
    auto_topup_target = max(float(X_SIGNAL_AUTO_USDC_TARGET), float(X_SIGNAL_USDC_SAFE_FLOOR))
    auto_topup_enabled = bool(getattr(fcb, "X_SIGNAL_AUTO_USDC_TOPUP_ENABLED", X_SIGNAL_AUTO_USDC_TOPUP_ENABLED))
    auto_topup_buy_gate = has_buy_signal and (has_buy_ready_on_cooldown or high_conviction)
    auto_topup_backoff_s = max(
        0,
        int(getattr(fcb, "X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS", X_SIGNAL_AUTO_USDC_FAIL_COOLDOWN_SECONDS)),
    )
    should_consider_auto_topup = (
        auto_topup_enabled
        and auto_topup_buy_gate
        and float(balances.usdc) < float(X_SIGNAL_USDC_SAFE_FLOOR)
    )
    print(
        f"{runtime._nanolog()}AUTO-USDC consider | enabled={auto_topup_enabled} "
        f"| has_buy_signal={has_buy_signal} | cooldown_ready={has_buy_ready_on_cooldown} "
        f"| high_conviction={high_conviction} | buy_gate={auto_topup_buy_gate} "
        f"| usdc=${float(balances.usdc):.2f} | safe_floor=${float(X_SIGNAL_USDC_SAFE_FLOOR):.2f} "
        f"| fail_backoff_s={auto_topup_backoff_s}"
    )
    auto_topup_attempted = False
    auto_topup_ok = False
    auto_topup_pre_usdc = float(balances.usdc)
    auto_topup_post_usdc = float(balances.usdc)
    if (
        should_consider_auto_topup
    ):
        if dry_run:
            balances = _project_balances_after_auto_usdc(
                balances,
                min_usdc=auto_topup_target,
                min_wmatic_value=float(X_SIGNAL_WMATIC_MIN_VALUE),
            )
        else:
            now_ts = float(time.time())
            backoff_until = float(_AUTO_USDC_FAILURE_STATE.get("next_retry_ts", 0.0) or 0.0)
            if backoff_until > now_ts:
                remaining_s = max(0.0, backoff_until - now_ts)
                print(
                    f"{runtime._nanolog()}AUTO-USDC skipped — failure backoff active "
                    f"(remaining={remaining_s:.0f}s)"
                )
                auto_topup_post_usdc = float(balances.usdc)
            else:
                auto_topup_attempted = True
                auto_topup_pre_usdc = float(balances.usdc)
                print(
                    f"{runtime._nanolog()}AUTO-USDC execution start | "
                    f"pre_usdc=${auto_topup_pre_usdc:.2f} target=${auto_topup_target:.2f}"
                )
                auto_topup_ok = fcb.ensure_usdc_for_x_signal(
                    min_usdc=auto_topup_target,
                    min_wmatic_value=float(X_SIGNAL_WMATIC_MIN_VALUE),
                    force=True,
                )
                balances = fcb.get_balances()
                auto_topup_post_usdc = float(balances.usdc)
                unchanged_usdc = abs(auto_topup_post_usdc - auto_topup_pre_usdc) < 0.01
                if auto_topup_ok:
                    _AUTO_USDC_FAILURE_STATE["next_retry_ts"] = 0.0
                    _AUTO_USDC_FAILURE_STATE["last_failure_usdc"] = -1.0
                    _AUTO_USDC_FAILURE_STATE["consecutive_failures"] = 0
                elif auto_topup_backoff_s > 0 and unchanged_usdc:
                    prev_failures = int(_AUTO_USDC_FAILURE_STATE.get("consecutive_failures", 0) or 0)
                    _AUTO_USDC_FAILURE_STATE["consecutive_failures"] = prev_failures + 1
                    _AUTO_USDC_FAILURE_STATE["last_failure_usdc"] = auto_topup_post_usdc
                    _AUTO_USDC_FAILURE_STATE["next_retry_ts"] = now_ts + float(auto_topup_backoff_s)
                fail_class = "none"
                if not auto_topup_ok:
                    fail_class = "floor_not_reached"
                    if unchanged_usdc:
                        fail_class = "no_balance_change"
                print(
                    f"{runtime._nanolog()}AUTO-USDC attempt summary | ok={auto_topup_ok} "
                    f"| fail_class={fail_class} | pre_usdc=${auto_topup_pre_usdc:.2f} "
                    f"| post_usdc=${auto_topup_post_usdc:.2f} | target=${auto_topup_target:.2f}"
                )
                if not auto_topup_ok:
                    print(
                        f"{runtime._nanolog()}AUTO-USDC top-up attempted but floor not reached "
                        f"(have ${balances.usdc:.2f}, target ${auto_topup_target:.2f})"
                    )
                else:
                    print(
                        f"{runtime._nanolog()}AUTO-USDC top-up successful "
                        f"(have ${balances.usdc:.2f}, target ${auto_topup_target:.2f})"
                    )

    print(f"🟦 X-SIGNAL EQUITY CHECK | Checking {len(assets)} assets")
    if not cfg_enabled:
        result = f"NO TRADE | followed_equities disabled (enabled=false in {fcb.FOLLOWED_EQUITIES_PATH})"
        print(f"🟦 X-SIGNAL EQUITY | {result}")
    elif not assets:
        result = "NO TRADE | no assets loaded (missing file, bad JSON, or empty assets[])"
        print(f"🟦 X-SIGNAL EQUITY | {result}")
    elif not eligible:
        result = (
            f"NO TRADE | no_asset_above_threshold (need abs(signal)>={min_strength:.2f}; "
            f"raise signal or lower min_signal_strength/env X_SIGNAL_EQUITY_MIN_STRENGTH)"
        )
        print(
            f"🟦 X-SIGNAL EQUITY | No valid plan this cycle "
            f"(reason: no_asset_above_threshold (>={min_strength:.2f}))"
        )
    else:
        # === PnL+ SPRINT OVERRIDE (high-conviction bypass) ===
        if high_conviction:
            print(
                f"🚀 HIGH-CONVICTION GAS OVERRIDE | {strong_thr:.2f}+ strength detected — bypassing {MAX_GWEI:.0f} gwei limit "
                "(PnL+ Sprint Mode, high return high conviction, net expected positive)"
            )

        has_strong_buy = any(
            float(a.signal_strength) > 0 and float(a.signal_strength) >= strong_thr for a in eligible
        )
        trader = tuned_trader
        min_trade_usdc = float(trader.config.min_trade_usdc)
        min_usdc = float(X_SIGNAL_USDC_MIN)

        force_floor = float(min_usdc)
        if has_strong_buy and balances.usdc < max(force_floor, min_trade_usdc):
            print(
                f"🟦 X-SIGNAL EQUITY | Auto-USDC insufficient for BUY equity "
                f"(USDC ${balances.usdc:.2f} < ${max(force_floor, min_trade_usdc):.2f}) — BUY paths may be skipped"
            )
            fcb._log_trade_skipped(
                f"USDC low (have ${balances.usdc:.2f}, need ${max(force_floor, min_trade_usdc):.2f})"
            )
        if (
            auto_topup_attempted
            and not auto_topup_ok
            and has_strong_buy
            and float(balances.usdc) < max(force_floor, min_trade_usdc)
        ):
            print(
                f"{runtime._nanolog()}X-SIGNAL EQUITY | short-circuit cycle after AUTO-USDC failure "
                f"(pre=${auto_topup_pre_usdc:.2f}, post=${auto_topup_post_usdc:.2f}, "
                f"need=${max(force_floor, min_trade_usdc):.2f})"
            )
            fcb._log_trade_skipped(
                f"x_signal_cycle_short_circuit (auto_usdc_failed; usdc={float(balances.usdc):.2f})"
            )
            return None

        if not dry_run and has_strong_buy:
            balances = fcb.get_balances()
            if float(balances.pol) < float(fcb.MIN_POL_FOR_GAS):
                if fcb.AUTO_TOPUP_POL:
                    if fcb.ensure_pol_for_trade(min_pol=float(fcb.MIN_POL_FOR_GAS)):
                        balances = fcb.get_balances()
                        if float(balances.pol) >= float(fcb.MIN_POL_FOR_GAS):
                            # POL recovered; BUY path remains eligible.
                            pass
                        else:
                            print(
                                f"{runtime._nanolog()}AUTO-POL reported success but POL still low "
                                f"(pol≈{float(balances.pol):.4f} < {fcb.MIN_POL_FOR_GAS:.4f}) — BUY paths skipped"
                            )
                            fcb._log_trade_skipped(
                                f"POL low for BUY path after top-up (pol={float(balances.pol):.4f}, min={fcb.MIN_POL_FOR_GAS:.4f})"
                            )
                    else:
                        print(
                            f"{runtime._nanolog()}AUTO-POL failed during X-SIGNAL prep "
                            f"(pol<{fcb.MIN_POL_FOR_GAS:.4f}) — BUY paths skipped"
                        )
                else:
                    print(
                        f"{runtime._nanolog()}POL low (pol≈{float(balances.pol):.4f} < {fcb.MIN_POL_FOR_GAS:.4f}) "
                        f"and AUTO_TOPUP_POL=false — BUY paths skipped"
                    )
                    fcb._log_trade_skipped(
                        f"POL low for BUY path (pol={float(balances.pol):.4f}, min={fcb.MIN_POL_FOR_GAS:.4f})"
                    )

        eligible_ordered = _order_eligible_x_signal_candidates(eligible, per_asset_cooldown_seconds=secs_order)
        
        print(f"{runtime._nanolog()}=== ELIGIBLE ASSET ORDERING ===")
        for _a in eligible_ordered:
            _sym = str(_a.symbol).strip()
            _sig = float(_a.signal_strength)
            _cd_ok = fcb.can_trade_asset(_sym, None, secs_order)
            _fe_thr_ord = float(
                getattr(tuned_trader.config, "force_eligible_threshold", X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD)
            )
            _is_fe = abs(_sig) >= _fe_thr_ord
            print(
                f"{runtime._nanolog()}  {_sym:12s} | sig={_sig:6.3f} | force_eligible={_is_fe:5} | cooldown_ok={_cd_ok:5}"
            )
        print(f"{runtime._nanolog()}=== END ORDERING ===\n")

        chain_notes: list[str] = []

        for a in eligible:
            hint = _polygon_chain_hint(str(a.symbol), str(a.token_address))
            if hint:
                chain_notes.append(hint)

        print(f"{runtime._nanolog()}=== BUILDING TRADE PLANS ===")
        plans = []
        for a in eligible_ordered:
            equity_balance = fcb.get_token_balance(a.token_address, int(a.decimals))
            sym = str(a.symbol).strip()
            is_buy = float(a.signal_strength) > 0
            if is_buy and skip_buys:
                reasons = ",".join(list(risk_ctx.get("reasons") or []))
                print(
                    f"{runtime._nanolog()}X-SIGNAL BUY SKIPPED | symbol={sym} | risk={risk_level} | "
                    f"reason={reasons or 'N/A'}"
                )
                continue
            if is_buy and medium_usdt_wmatic_guard and sym in ("WMATIC", "WMATIC_ALPHA"):
                reasons = ",".join(list(risk_ctx.get("reasons") or []))
                print(
                    f"{runtime._nanolog()}X-SIGNAL BUY SKIPPED | symbol={sym} | risk={risk_level} | "
                    f"reason={reasons or 'N/A'}"
                )
                continue
            asset_buy_mult = 0.0 if (is_buy and medium_usdt_wmatic_guard and sym in ("WMATIC", "WMATIC_ALPHA")) else buy_mult
            plan, plan_block = _invoke_equity_build_plan(
                trader,
                EquityBuildPlanParams.for_eligible_asset(
                    a,
                    usdc_balance=balances.usdc,
                    usdt_balance=balances.usdt,
                    equity_balance=equity_balance,
                    wallet_address_for_gas=fcb.WALLET,
                    can_trade_asset=fcb.can_trade_asset,
                    allow_high_gas_override=high_conviction,
                    trade_size_multiplier=(asset_buy_mult if is_buy else 1.0),
                    buy_risk_level=(risk_level if is_buy else None),
                ),
            )
            if plan:
                # Plan trade_size already uses FIXED SIZING $12–$20 (signal_equity_trader); never re-expand to full USDC.
                dynamic_trade_size_usdc = float(plan.trade_size)
                if str(plan.direction) == "USDC_TO_EQUITY":
                    dynamic_trade_size_usdc = min(dynamic_trade_size_usdc, float(balances.usdc))
                    logger.info(
                        f"X-SIGNAL EQUITY BUY: {sym} | Strength {abs(float(a.signal_strength)):.2f} | "
                        f"Size: ${dynamic_trade_size_usdc:.2f}"
                    )
                secs_plan = int(trader.config.per_asset_cooldown_seconds)
                decision = TradeDecision(
                    direction=plan.direction,
                    amount_in=(
                        int(dynamic_trade_size_usdc * 1_000_000)
                        if str(plan.direction) == "USDC_TO_EQUITY"
                        else plan.amount_in
                    ),
                    trade_size=dynamic_trade_size_usdc,
                    message=plan.message,
                    token_in=plan.token_in,
                    token_out=plan.token_out,
                    cooldown_asset=(sym, secs_plan),
                )
                plans.append((decision, float(a.signal_strength)))
            else:
                logger.warning(f"PLAN FAILED for {sym}: {plan_block or 'unknown'}")

        if plans:
            # BEST PLAN WINS (highest signal)
            plans.sort(key=lambda x: x[1], reverse=True)
            decision = plans[0][0]
        else:
            decision = None

        if not decision:
            summary_bits: list[str] = []
            if chain_notes:
                summary_bits.append("chain: " + " | ".join(chain_notes))
            if balances.usdc < float(trader.config.min_trade_usdc):
                summary_bits.append(f"usdc low: ${balances.usdc:.2f}")
            if high_conviction and dry_run:
                print(
                    f"[nanoclaw] gas override active ({high_conviction_threshold:.2f}+ high conviction; "
                    f"bypassing {MAX_GWEI:.0f} gwei block)"
                )
            print(f"{runtime._nanolog()}X-SIGNAL EQUITY | No valid plan this cycle (reason: {' | '.join(summary_bits) or 'no_plan'})")
            return None

        return decision


def evaluate_x_signal_equity_trade(
    balances: Balances,
    *,
    trader: SignalEquityTrader = X_SIGNAL_EQUITY_TRADER,
) -> Optional[EquityTradePlan]:
    """Same eligibility + sorting as `try_x_signal_equity_decision` without diagnostic prints."""
    fcb = _cs_mod()
    if not fcb.ENABLE_X_SIGNAL_EQUITY:
        return None
    cfg = fcb._load_followed_equities_json_dict()
    cfg_enabled = bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
    if not cfg_enabled:
        return None
    min_strength = fcb._effective_equity_signal_min(cfg)
    strong_thr = float(trader.config.strong_signal_threshold)
    force_high_conviction = bool(trader.config.force_high_conviction)
    high_conviction_threshold = float(trader.config.high_conviction_threshold)
    force_eligible_thr = float(trader.config.force_eligible_threshold)
    assets_seq = trader.load_followed_equities()
    _, eligible = _sorted_and_eligible_equities(
        assets_seq,
        min_strength,
        strong_thr,
        force_high_conviction=force_high_conviction,
        high_conviction_threshold=high_conviction_threshold,
        force_eligible_threshold=force_eligible_thr,
    )
    if not eligible:
        return None
    high_conviction = any(
        float(a.signal_strength) >= high_conviction_threshold for a in eligible if float(a.signal_strength) > 0
    )
    tuned = fcb._tuned_signal_equity_trader(min_strength)
    eligible_ordered = _order_eligible_x_signal_candidates(
        eligible,
        per_asset_cooldown_seconds=int(tuned.config.per_asset_cooldown_seconds),
    )
    for a in eligible_ordered:
        equity_balance = fcb.get_token_balance(a.token_address, int(a.decimals))
        sym = str(a.symbol).strip()
        plan = tuned.build_plan(
            symbol=sym,
            token_address=str(a.token_address).strip(),
            token_decimals=int(a.decimals),
            signal_strength=float(a.signal_strength),
            earnings_proximity_days=a.earnings_days,
            current_price_usd=a.current_price_usd,
            usdc_balance=balances.usdc,
            equity_balance=equity_balance,
            wallet_address_for_gas=fcb.WALLET,
            can_trade_asset=fcb.can_trade_asset,
            usdt_balance=balances.usdt,
            allow_high_gas_override=high_conviction,
            upside_pct=a.upside_pct,
        )
       
        if plan:
            # Preserve current helper behavior (no execution decision return from this evaluator).
            break
    return None


