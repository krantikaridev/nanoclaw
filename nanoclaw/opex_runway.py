"""Wallet stable runway vs monthly opex burn (Ankr, hosting, Cursor, Grok)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import config as cfg

_DAYS_PER_MONTH = 30.0
_OPEX_RUNWAY_LOG_PREFIX = "[nanoclaw] OPEX RUNWAY ALERT"
_STAGE_WALLET_DEFAULT = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"


@dataclass(frozen=True)
class OpexLineItem:
    label: str
    monthly_usd: float


@dataclass(frozen=True)
class OpexRunwayAssessment:
    wallet: str
    stables_usd: float
    monthly_total_usd: float
    daily_burn_usd: float
    alert_threshold_usd: float
    alert_days: int
    runway_days: float
    line_items: tuple[OpexLineItem, ...]
    alert_active: bool


def _finite_nonneg(value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v < 0.0:
        return 0.0
    return v


def opex_line_items(
    *,
    opex_monthly: float | None = None,
    cursor_monthly: float | None = None,
    grok_monthly: float | None = None,
    hosting_monthly: float | None = None,
) -> tuple[OpexLineItem, ...]:
    items = (
        OpexLineItem(
            "Ankr/RPC misc",
            _finite_nonneg(
                opex_monthly
                if opex_monthly is not None
                else getattr(cfg, "OPEX_MONTHLY_USD", 0.0)
            ),
        ),
        OpexLineItem(
            "Cursor",
            _finite_nonneg(
                cursor_monthly
                if cursor_monthly is not None
                else getattr(cfg, "OPEX_CURSOR_MONTHLY_USD", 0.0)
            ),
        ),
        OpexLineItem(
            "Grok",
            _finite_nonneg(
                grok_monthly
                if grok_monthly is not None
                else getattr(cfg, "OPEX_GROK_MONTHLY_USD", 0.0)
            ),
        ),
        OpexLineItem(
            "Hosting",
            _finite_nonneg(
                hosting_monthly
                if hosting_monthly is not None
                else getattr(cfg, "OPEX_HOSTING_MONTHLY_USD", 0.0)
            ),
        ),
    )
    return items


def total_monthly_opex_usd(
    *,
    opex_monthly: float | None = None,
    cursor_monthly: float | None = None,
    grok_monthly: float | None = None,
    hosting_monthly: float | None = None,
) -> float:
    return sum(item.monthly_usd for item in opex_line_items(
        opex_monthly=opex_monthly,
        cursor_monthly=cursor_monthly,
        grok_monthly=grok_monthly,
        hosting_monthly=hosting_monthly,
    ))


def format_wallet_short(wallet: str) -> str:
    w = str(wallet or "").strip()
    if len(w) <= 12:
        return w
    return f"{w[:6]}…{w[-4:]}"


def compute_runway_days(stables_usd: float, monthly_total_usd: float) -> float:
    daily = float(monthly_total_usd) / _DAYS_PER_MONTH
    if daily <= 0.0:
        return float("inf")
    return float(stables_usd) / daily


def runway_alert_threshold_usd(monthly_total_usd: float, alert_days: int) -> float:
    days = max(0, int(alert_days))
    monthly = max(0.0, float(monthly_total_usd))
    return (monthly / _DAYS_PER_MONTH) * float(days)


def assess_opex_runway(
    stables_usd: float,
    *,
    wallet: str | None = None,
    alert_days: int | None = None,
    opex_monthly: float | None = None,
    cursor_monthly: float | None = None,
    grok_monthly: float | None = None,
    hosting_monthly: float | None = None,
) -> OpexRunwayAssessment:
    items = opex_line_items(
        opex_monthly=opex_monthly,
        cursor_monthly=cursor_monthly,
        grok_monthly=grok_monthly,
        hosting_monthly=hosting_monthly,
    )
    monthly_total = sum(item.monthly_usd for item in items)
    days = int(
        alert_days if alert_days is not None else getattr(cfg, "OPEX_RUNWAY_ALERT_DAYS", 14)
    )
    daily_burn = monthly_total / _DAYS_PER_MONTH if monthly_total > 0.0 else 0.0
    threshold = runway_alert_threshold_usd(monthly_total, days)
    stables = max(0.0, float(stables_usd))
    runway = compute_runway_days(stables, monthly_total)
    alert_active = bool(monthly_total > 0.0 and stables + 1e-9 < threshold)
    wallet_addr = str(wallet if wallet is not None else getattr(cfg, "WALLET", _STAGE_WALLET_DEFAULT))
    return OpexRunwayAssessment(
        wallet=wallet_addr,
        stables_usd=stables,
        monthly_total_usd=monthly_total,
        daily_burn_usd=daily_burn,
        alert_threshold_usd=threshold,
        alert_days=days,
        runway_days=runway,
        line_items=items,
        alert_active=alert_active,
    )


def format_opex_runway_message(assessment: OpexRunwayAssessment) -> str:
    wallet_short = format_wallet_short(assessment.wallet)
    lines = [
        f"{_OPEX_RUNWAY_LOG_PREFIX} | wallet={wallet_short} (Polygon stage)",
        f"stables_usd=${assessment.stables_usd:.2f}",
        f"runway_days={assessment.runway_days:.1f}",
        f"alert_threshold=${assessment.alert_threshold_usd:.2f} ({assessment.alert_days}d burn)",
        "line_items:",
    ]
    for item in assessment.line_items:
        if item.monthly_usd <= 0.0:
            continue
        lines.append(f"  - {item.label}: ${item.monthly_usd:.2f}/mo")
    lines.append(f"monthly_total=${assessment.monthly_total_usd:.2f}/mo")
    return " | ".join(lines)


def format_opex_runway_telegram(assessment: OpexRunwayAssessment) -> str:
    wallet_short = format_wallet_short(assessment.wallet)
    item_lines = [
        f"{item.label}: ${item.monthly_usd:.2f}/mo"
        for item in assessment.line_items
        if item.monthly_usd > 0.0
    ]
    body = (
        f"wallet {wallet_short} (Polygon)\n"
        f"stables ${assessment.stables_usd:.2f}\n"
        f"runway {assessment.runway_days:.1f} days\n"
        f"threshold ${assessment.alert_threshold_usd:.2f} ({assessment.alert_days}d)\n"
        f"monthly total ${assessment.monthly_total_usd:.2f}\n"
        + ("\n".join(item_lines) if item_lines else "no opex line items configured")
    )
    return f"<b>nanoclaw OPEX RUNWAY</b>\n<pre>{body}</pre>"


def load_latest_stables_from_portfolio_history(
    csv_path: Path | str = "portfolio_history.csv",
) -> float | None:
    """Last snapshot stables (USDT+USDC) from portfolio_history.csv."""
    path = Path(csv_path)
    if not path.is_file():
        return None
    try:
        import csv

        last_usdt = last_usdc = None
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    last_usdt = float(row.get("usdt", "") or 0.0)
                    last_usdc = float(row.get("usdc", "") or 0.0)
                except (TypeError, ValueError):
                    continue
        if last_usdt is None or last_usdc is None:
            return None
        stable = float(last_usdt) + float(last_usdc)
        if not math.isfinite(stable):
            return None
        return stable
    except OSError:
        return None


def resolve_stables_usd(
    *,
    override: float | None = None,
    csv_path: Path | str | None = None,
) -> float | None:
    if override is not None and math.isfinite(float(override)):
        return max(0.0, float(override))
    try:
        from scripts.pnl_report import compute_authoritative_total_in_process

        live = compute_authoritative_total_in_process()
        if live is not None:
            return float(live["stable_usd"])
    except Exception:
        pass
    return load_latest_stables_from_portfolio_history(csv_path or "portfolio_history.csv")


def run_opex_runway_check(
    *,
    stables_usd: float | None = None,
    dry_run: bool = False,
    send_telegram: bool | None = None,
    now_utc: datetime | None = None,
) -> tuple[OpexRunwayAssessment | None, int]:
    """Evaluate runway; log/Telegram when below threshold. Returns (assessment, exit_code)."""
    _ = now_utc  # reserved for future dedupe / cron windows
    resolved = resolve_stables_usd(override=stables_usd)
    if resolved is None:
        print("[nanoclaw] OPEX RUNWAY | stables_usd unavailable (no RPC / portfolio_history)")
        return None, 2

    assessment = assess_opex_runway(resolved)
    if assessment.monthly_total_usd <= 0.0:
        print(
            "[nanoclaw] OPEX RUNWAY | monthly opex not configured "
            "(set OPEX_MONTHLY_USD and related keys)"
        )
        return assessment, 0

    msg = format_opex_runway_message(assessment)
    if not assessment.alert_active:
        print(f"[nanoclaw] OPEX RUNWAY OK | {msg.split(' | ', 1)[1]}")
        return assessment, 0

    print(msg)
    telegram_enabled = bool(
        send_telegram
        if send_telegram is not None
        else getattr(cfg, "OPEX_RUNWAY_TELEGRAM_ENABLED", False)
    )
    if telegram_enabled and not dry_run:
        try:
            from modules.agent_layer import _telegram_send_html

            _telegram_send_html(format_opex_runway_telegram(assessment))
        except Exception:
            pass
    return assessment, 1
