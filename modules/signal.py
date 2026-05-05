"""X-Signal equity eligibility, auto-USDC, planning, evaluation helpers."""

from __future__ import annotations

import asyncio
import json
import logging
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
    X_SIGNAL_EQUITY_TRADER,
    X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD,
    X_SIGNAL_FORCE_HIGH_CONVICTION,
    X_SIGNAL_FORCE_HIGH_CONVICTION_THRESHOLD,
    X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC,
    X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC,
    X_SIGNAL_USDC_MIN,
    X_SIGNAL_USDC_SAFE_FLOOR,
    X_SIGNAL_WMATIC_MIN_VALUE,
    approve_and_swap,
    w3,
)

logger = logging.getLogger(__name__)


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
    """If USDC is below ``min_usdc`` and (a strong X-Signal BUY is active or force=True), swap WMATIC→USDC (preferred) or USDT→USDC."""
    fac = _cs_mod()
    balances = fac.get_balances()
    if balances.usdc >= min_usdc:
        return True
    if not force and not _facade_strong_buy_present():
        return False

    gst = fac.GAS_PROTECTOR.get_safe_status(
        address=fac.WALLET, urgent=False, min_pol=fac.MIN_POL_FOR_GAS
    )
    if not gst.get("ok", False):
        print(f"{runtime._nanolog()}AUTO-USDC skipped — gas/POL guard")
        return False

    key, _key_source = cfg.resolve_private_key()
    if not key:
        print(f"{runtime._nanolog()}AUTO-USDC skipped — no private key")
        return False

    try:
        wmatic_price = float(fac.get_live_wmatic_price())
    except Exception:
        wmatic_price = 0.0
    if wmatic_price <= 0:
        print(f"{runtime._nanolog()}AUTO-USDC skipped — WMATIC price unavailable")
        return False

    shortfall = max(0.0, float(min_usdc) - float(balances.usdc))
    # Gas-optimized: if we need to populate, do a meaningful swap (avoid $0.40 USDC drips).
    target_usd = max(shortfall * 1.05, float(AUTO_POPULATE_USDC_AMOUNT))
    wmatic_usd = balances.wmatic * wmatic_price

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
        return asyncio.run(coro)

    use_wmatic_first = wmatic_usd >= float(min_wmatic_value)
    if use_wmatic_first:
        swap_usd = min(wmatic_usd * 0.95, target_usd)
        wmatic_to_swap = min(balances.wmatic * 0.95, swap_usd / wmatic_price)
        amount_wei = int(wmatic_to_swap * 1e18)
        if amount_wei > 0:
            print(f"🔄 AUTO-USDC | Swapping ${swap_usd:.2f} from WMATIC → USDC (gas optimized)")
            ok = _run(_swap_wmatic(amount_wei))
            if ok:
                print(f"🔄 AUTO-USDC | Swapped ${swap_usd:.2f} from WMATIC → USDC (gas optimized)")
            if ok and fac.get_balances().usdc >= min_usdc:
                return True
        after = fac.get_balances()
        if after.usdt >= 0.5:
            print("🔄 AUTO-USDC | Using USDT path (fallback)")
            usdt_amt = min(after.usdt * 0.95, target_usd)
            ok2 = _run(_swap_usdt(int(usdt_amt * 1_000_000)))
            return ok2 and fac.get_balances().usdc >= min_usdc
        return fac.get_balances().usdc >= min_usdc

    print("🔄 AUTO-USDC | Using USDT path (fallback)")
    after = fac.get_balances()
    usdt_amt = min(after.usdt * 0.95, target_usd)
    ok = _run(_swap_usdt(int(usdt_amt * 1_000_000)))
    return ok and fac.get_balances().usdc >= min_usdc


def _project_balances_after_auto_usdc(
    balances: Balances,
    *,
    min_usdc: float,
    min_wmatic_value: float,
) -> Balances:
    """Mirror ``ensure_usdc_for_x_signal`` guards and sizing without swaps (dry-run fair USDC for equity plans)."""
    if balances.usdc >= min_usdc:
        return balances
    if not _facade_strong_buy_present():
        return balances

    fac = _cs_mod()
    gst = fac.GAS_PROTECTOR.get_safe_status(
        address=fac.WALLET, urgent=False, min_pol=fac.MIN_POL_FOR_GAS
    )
    if not gst.get("ok", False):
        return balances

    key, _key_source = cfg.resolve_private_key()
    if not key:
        return balances

    try:
        wmatic_price = float(fac.get_live_wmatic_price())
    except Exception:
        return balances
    if wmatic_price <= 0:
        return balances

    shortfall = max(0.0, float(min_usdc) - float(balances.usdc))
    target_usd = max(shortfall * 1.05, float(AUTO_POPULATE_USDC_AMOUNT))
    wmatic_usd = balances.wmatic * wmatic_price

    use_wmatic_first = wmatic_usd >= float(min_wmatic_value)
    if use_wmatic_first:
        swap_usd = min(wmatic_usd * 0.95, target_usd)
        wmatic_to_swap = min(balances.wmatic * 0.95, swap_usd / wmatic_price)
        if wmatic_to_swap > 0:
            est_usdc_out = min(wmatic_to_swap * wmatic_price, swap_usd)
            if balances.usdc + est_usdc_out >= min_usdc:
                return Balances(
                    usdt=balances.usdt,
                    wmatic=balances.wmatic - wmatic_to_swap,
                    pol=balances.pol,
                    usdc=balances.usdc + est_usdc_out,
                )
        if balances.usdt >= 0.5:
            usdt_amt = min(balances.usdt * 0.95, target_usd)
            if usdt_amt > 0 and balances.usdc + usdt_amt >= min_usdc:
                return Balances(
                    usdt=balances.usdt - usdt_amt,
                    wmatic=balances.wmatic,
                    pol=balances.pol,
                    usdc=balances.usdc + usdt_amt,
                )
        return balances

    if balances.usdt >= 0.5:
        usdt_amt = min(balances.usdt * 0.95, target_usd)
        if usdt_amt > 0 and balances.usdc + usdt_amt >= min_usdc:
            return Balances(
                usdt=balances.usdt - usdt_amt,
                wmatic=balances.wmatic,
                pol=balances.pol,
                usdc=balances.usdc + usdt_amt,
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

    # Proactive USDC maintenance runs before any eligibility/plan logic that uses balances.
    if not dry_run:
        probe = fcb.get_balances()
        if probe.usdc < X_SIGNAL_USDC_SAFE_FLOOR:
            print(
                f"🚀 PROACTIVE USDC TOP-UP triggered (have ${probe.usdc:.2f} < ${X_SIGNAL_USDC_SAFE_FLOOR:.2f}, "
                f"target ${X_SIGNAL_AUTO_USDC_TARGET:.2f})"
            )
            fcb.ensure_usdc_for_x_signal(
                min_usdc=X_SIGNAL_AUTO_USDC_TARGET,
                min_wmatic_value=X_SIGNAL_WMATIC_MIN_VALUE,
                force=True,
            )
        balances = fcb.get_balances()

    cfg = fcb._load_followed_equities_json_dict()
    cfg_enabled = bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
    min_strength = fcb._effective_equity_signal_min(cfg)
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
        total_portfolio_usd=max(
            0.0,
            float(balances.total_portfolio_usd) - snapshot_usdc + onchain_preferred_usdc,
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
            # Force USDC top-up for high-conviction.
            if dry_run:
                balances = _project_balances_after_auto_usdc(
                    balances,
                    min_usdc=X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC,
                    min_wmatic_value=X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC,
                )
            else:
                topup_ok = fcb.ensure_usdc_for_x_signal(
                    min_usdc=X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC,
                    min_wmatic_value=X_SIGNAL_HIGH_CONVICTION_PREP_MIN_WMATIC,
                )
                balances = fcb.get_balances()
                if not topup_ok and balances.usdc < X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC:
                    print(
                        "🟦 X-SIGNAL EQUITY | Auto-USDC failed during HIGH-CONVICTION prep "
                        "(PnL+ Sprint Mode, high return high conviction)"
                    )
                    fcb._log_trade_skipped(
                        f"AUTO-USDC failed during high-conviction prep "
                        f"(have ${balances.usdc:.2f}, need ${X_SIGNAL_HIGH_CONVICTION_PREP_MIN_USDC:.2f})"
                    )

        has_strong_buy = any(
            float(a.signal_strength) > 0 and float(a.signal_strength) >= strong_thr for a in eligible
        )
        trader = tuned_trader
        min_trade_usdc = float(trader.config.min_trade_usdc)
        min_usdc = float(X_SIGNAL_USDC_MIN)
        required_usdc_floor = max(float(min_usdc), min_trade_usdc)
        # Align auto-USDC with equity sizing: never aim below min_trade_usdc.
        auto_usdc_target = required_usdc_floor

        force_floor = float(min_usdc)
        if has_strong_buy and balances.usdc < max(force_floor, auto_usdc_target):
            if dry_run:
                balances = _project_balances_after_auto_usdc(
                    balances,
                    min_usdc=max(force_floor, auto_usdc_target),
                    min_wmatic_value=float(X_SIGNAL_WMATIC_MIN_VALUE),
                )
            else:
                topup_ok = fcb.ensure_usdc_for_x_signal(
                    min_usdc=max(force_floor, auto_usdc_target),
                    min_wmatic_value=float(X_SIGNAL_WMATIC_MIN_VALUE),
                )
                balances = fcb.get_balances()
                if not topup_ok and balances.usdc < max(force_floor, min_trade_usdc):
                    print(
                        "🟦 X-SIGNAL EQUITY | Auto-USDC attempt failed "
                        "(guard/tx) — BUY paths may be skipped"
                    )
                    fcb._log_trade_skipped(
                        f"AUTO-USDC failed (have ${balances.usdc:.2f}, need ${max(force_floor, min_trade_usdc):.2f})"
                    )
            if balances.usdc >= max(force_floor, min_trade_usdc):
                if dry_run:
                    print(
                        "🟦 X-SIGNAL EQUITY | DRY-RUN: projected post auto-USDC | Proceeding with BUY analysis"
                    )
                else:
                    print("🟦 X-SIGNAL EQUITY | USDC ensured via WMATIC/USDT | Proceeding with BUY")
            else:
                print(
                    f"🟦 X-SIGNAL EQUITY | Auto-USDC insufficient for BUY equity "
                    f"(USDC ${balances.usdc:.2f} < ${max(force_floor, min_trade_usdc):.2f}) — BUY paths skipped"
                )
                fcb._log_trade_skipped(
                    f"USDC low (have ${balances.usdc:.2f}, need ${max(force_floor, min_trade_usdc):.2f})"
                )

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

        secs_order = int(trader.config.per_asset_cooldown_seconds)
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


