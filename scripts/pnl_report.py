#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys

# Ensure repo root is importable when this script is run as `python scripts/pnl_report.py`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.baseline import resolve_portfolio_baseline_usd  # noqa: E402

LOG_FILE = "real_cron.log"
PORTFOLIO_HISTORY_FILE = "portfolio_history.csv"
SESSION_BASELINE_FILE = "portfolio_session_baseline.json"
FE_USD_SPOT_CACHE_FILE = ".runtime/fe_usd_spot_cache.json"
PNL_FLOW_EVENTS_FILE = ".runtime/pnl_flow_events.jsonl"
_MARK_DELTA_SPOT_PCT_THRESHOLD = 0.01
_FLOW_STABLE_EXPLAIN_RATIO = 0.6
_MAX_REASONABLE_BALANCE_COMPONENT = 10_000_000.0
MANUAL_PATTERN = re.compile(
    r"MANUAL CORRECT BALANCE.*USDC=\$?([\d.]+).*WMATIC=\$?([\d.]+).*USDT=\$?([\d.]+).*Source=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
WALLET_PATTERN = re.compile(r"WALLET BALANCE.*USDC=\$?([\d.]+)")
# Cleanup #1 (May 2026): the authoritative source for the CURRENT TOTAL is now
# ``modules.runtime.compute_authoritative_total_usd(get_balances())``, called
# in-process via ``compute_authoritative_total_in_process()`` below. The two regex
# patterns here are retained as a READ-ONLY FALLBACK ONLY — for parsing existing
# historical ``real_cron.log`` rows when the in-process call is unavailable
# (e.g. RPC down on the operator's VM, no live web3 client in test env).
# Do NOT add this regex as a primary path for any new caller.
AUTHORITATIVE_TOTAL_PATTERN_V2 = re.compile(
    r"WALLET TOTAL USD\s*\|\s*TOTAL=\$?([\d.]+)\s*\|\s*USDT=\$?([\d.]+)\s*\|\s*USDC=\$?([\d.]+)\s*\|\s*"
    r"STABLE_USD=\$?([\d.]+)\s*\|\s*WMATIC=([\d.]+)",
    re.IGNORECASE,
)
# Legacy line without STABLE_USD (older logs before v2.8 PnL clarity).
AUTHORITATIVE_TOTAL_PATTERN_V1 = re.compile(
    r"WALLET TOTAL USD\s*\|\s*TOTAL=\$?([\d.]+)\s*\|\s*USDT=\$?([\d.]+)\s*\|\s*USDC=\$?([\d.]+)\s*\|\s*WMATIC=([\d.]+)",
    re.IGNORECASE,
)
REAL_PATTERN = re.compile(
    r"Real USDT:\s*\$?([\d.]+)\s*\|\s*USDC:\s*\$?([\d.]+)\s*\|\s*WMATIC:\s*\$?([\d.]+)",
    re.IGNORECASE,
)
_LOG_CAL_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s")
_FE_USD_COMPONENT_RE = re.compile(r"FE_USD=\$?([\d.]+)")
_AUTO_FLOOR_UPDATE_RE = re.compile(
    r"FE_USD AUTO_FLOOR_UPDATE\s*\|\s*sym=([^|\s]+)\s*\|\s*last_good_spot=([\d.]+)"
)


@dataclass(frozen=True)
class BalanceSnapshot:
    usdt: float
    usdc: float
    wmatic: float
    total: float
    source: str
    logger_source: str | None = None
    # When set (WALLET TOTAL USD v2 log), explicit USDT+USDC from runtime; else infer from usdt+usdc.
    stable_usd_hint: float | None = None


def extract_snapshots(log_file: Path) -> list[BalanceSnapshot]:
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    snapshots: list[BalanceSnapshot] = []
    pending_wallet: tuple[int, float] | None = None

    for idx, line in enumerate(lines):
        authoritative_total_match = AUTHORITATIVE_TOTAL_PATTERN_V2.search(line)
        if authoritative_total_match:
            total = float(authoritative_total_match.group(1))
            usdt = float(authoritative_total_match.group(2))
            usdc = float(authoritative_total_match.group(3))
            stable_hint = float(authoritative_total_match.group(4))
            wmatic = float(authoritative_total_match.group(5))
            snapshots.append(
                BalanceSnapshot(
                    usdt=usdt,
                    usdc=usdc,
                    wmatic=wmatic,
                    total=total,
                    source="authoritative_total",
                    stable_usd_hint=stable_hint,
                )
            )
            pending_wallet = None
            continue

        authoritative_total_match = AUTHORITATIVE_TOTAL_PATTERN_V1.search(line)
        if authoritative_total_match:
            total = float(authoritative_total_match.group(1))
            usdt = float(authoritative_total_match.group(2))
            usdc = float(authoritative_total_match.group(3))
            wmatic = float(authoritative_total_match.group(4))
            snapshots.append(
                BalanceSnapshot(
                    usdt=usdt,
                    usdc=usdc,
                    wmatic=wmatic,
                    total=total,
                    source="authoritative_total",
                    stable_usd_hint=None,
                )
            )
            pending_wallet = None
            continue

        manual_match = MANUAL_PATTERN.search(line)
        if manual_match:
            usdc = float(manual_match.group(1))
            wmatic = float(manual_match.group(2))
            usdt = float(manual_match.group(3))
            logger_source = manual_match.group(4)
            snapshots.append(
                BalanceSnapshot(
                    usdt=usdt,
                    usdc=usdc,
                    wmatic=wmatic,
                    total=usdc + usdt + wmatic,
                    source="manual",
                    logger_source=logger_source,
                )
            )
            continue

        wallet_match = WALLET_PATTERN.search(line)
        if wallet_match:
            pending_wallet = (idx, float(wallet_match.group(1)))
            continue

        real_match = REAL_PATTERN.search(line)
        if not real_match:
            continue

        usdt = float(real_match.group(1))
        usdc = float(real_match.group(2))
        wmatic = float(real_match.group(3))
        source = "real"

        if pending_wallet and (idx - pending_wallet[0]) <= 5:
            usdc = pending_wallet[1]
            source = "paired"
        pending_wallet = None

        snapshots.append(
            BalanceSnapshot(
                usdt=usdt,
                usdc=usdc,
                wmatic=wmatic,
                total=usdc + usdt + wmatic,
                source=source,
            )
        )

    return snapshots


def _source_rank(snapshot: BalanceSnapshot) -> int:
    if snapshot.source == "authoritative_total":
        return -1
    # Treat direct real and paired wallet+real as the same "live" class.
    # Recency is resolved in ``get_current_balance``.
    if snapshot.source in {"paired", "real"}:
        return 0
    if snapshot.source == "manual" and snapshot.logger_source in {"BotLogger", "AutoLogger"}:
        return 1
    return 2


def _source_label(snapshot: BalanceSnapshot) -> str:
    if snapshot.source == "authoritative_total":
        return "RUNTIME WALLET TRUTH (TOTAL USD)"
    if snapshot.source == "paired":
        return "ON-CHAIN LIVE (WALLET+REAL paired)"
    if snapshot.source == "real":
        return "ON-CHAIN LIVE (Real USDT line)"
    if snapshot.source == "manual" and snapshot.logger_source:
        return f"MANUAL ({snapshot.logger_source})"
    return "MANUAL"


def _is_usable_snapshot(snapshot: BalanceSnapshot) -> bool:
    values = (snapshot.usdt, snapshot.usdc, snapshot.wmatic, snapshot.total)
    if not all(math.isfinite(float(v)) for v in values):
        return False
    if any(float(v) < 0.0 for v in values):
        return False
    if max(float(snapshot.usdt), float(snapshot.usdc), float(snapshot.wmatic)) > _MAX_REASONABLE_BALANCE_COMPONENT:
        return False
    if snapshot.total <= 5:
        return False
    return True


def _stable_usd_for_snapshot(snapshot: BalanceSnapshot) -> float:
    if snapshot.stable_usd_hint is not None:
        return float(snapshot.stable_usd_hint)
    return float(snapshot.usdt) + float(snapshot.usdc)


def _print_balance_block(bal: dict) -> None:
    print(f"💰 CURRENT BALANCE  (source: {bal['source']})")
    print(f"   Stables USD (USDT+USDC): ${float(bal['stable_usd']):.2f}")
    print(f"   USDC:   ${float(bal['usdc']):.2f}")
    print(f"   USDT:   ${float(bal['usdt']):.2f}")
    print(f"   WMATIC: {float(bal['wmatic']):.6f} (qty, native units — not USD)")
    print(f"   TOTAL:  ${float(bal['total']):.2f}")
    if bal.get("rpc_read_suspect"):
        print(
            "   ⚠️  RPC read suspect: near-zero stables but material TOTAL "
            "(compare MetaMask / Polygonscan; fix RPC in .env — see docs/readme-vm-update.md)."
        )


def compute_authoritative_total_in_process() -> dict | None:
    """Live in-process WALLET TOTAL USD via ``runtime.compute_authoritative_total_usd``.

    Cleanup #1 (May 2026): this is the canonical path for ``nanopnl`` /
    ``nanostatus`` / ``nanodaily`` to read the CURRENT total. It calls the same
    helper the bot uses to emit ``WALLET TOTAL USD`` in ``real_cron.log`` and to
    write ``portfolio_history.csv::total_value``, so the four touchpoints
    (compute → log → CSV → report) cannot drift.

    Returns ``None`` when the in-process compute is unusable (no RPC, RPC error,
    near-zero total) so the caller falls through to the regex-based historical
    parser as a graceful safety net.
    """
    try:
        from modules import runtime
    except Exception:
        return None
    try:
        balances = runtime.get_balances()
        total = float(runtime.compute_authoritative_total_usd(balances))
    except Exception:
        return None
    # Sanity: matches ``_is_usable_snapshot`` total floor; a near-zero total here
    # means the RPC reads silently failed (``get_token_balance`` swallows errors)
    # and we should defer to the historical-log fallback rather than report a
    # bogus zero to the operator.
    if not math.isfinite(total) or total <= 5.0:
        return None
    usdt = float(balances.usdt)
    usdc = float(balances.usdc)
    stable_usd = usdt + usdc
    return {
        "usdt": usdt,
        "usdc": usdc,
        "wmatic": float(balances.wmatic),
        "total": total,
        "source": "RUNTIME WALLET TRUTH (in-process compute_authoritative_total_usd)",
        "stable_usd": stable_usd,
        "rpc_read_suspect": bool(stable_usd < 5.0 and total > 45.0),
    }


def get_current_balance():
    # Cleanup #1: prefer the in-process authoritative compute. Falls through to the
    # regex-based historical parser when RPC is unavailable (e.g. test env, VM RPC
    # outage), preserving prior behavior as a safety net.
    in_process = compute_authoritative_total_in_process()
    if in_process is not None:
        return in_process

    snapshots = extract_snapshots(Path(LOG_FILE))
    if not snapshots:
        return None

    usable = [snapshot for snapshot in snapshots if _is_usable_snapshot(snapshot)]
    if not usable:
        return None

    # Prefer live on-chain snapshots whenever available; within a rank, keep the most recent snapshot.
    best_rank = min(_source_rank(snapshot) for snapshot in usable)
    chosen = next(
        snapshot for snapshot in reversed(usable) if _source_rank(snapshot) == best_rank
    )
    stable_usd = _stable_usd_for_snapshot(chosen)
    rpc_read_suspect = bool(
        chosen.source == "authoritative_total"
        and stable_usd < 5.0
        and float(chosen.total) > 45.0
    )
    return {
        "usdt": chosen.usdt,
        "usdc": chosen.usdc,
        "wmatic": chosen.wmatic,
        "total": chosen.total,
        "source": _source_label(chosen),
        "stable_usd": stable_usd,
        "rpc_read_suspect": rpc_read_suspect,
    }


def print_daily_summary(*, reset_session: bool = False, lookback: str | None = None) -> int:
    bal = get_current_balance()
    if not bal:
        print("No valid balance found.")
        return 0

    total = float(bal["total"])
    _print_balance_block(bal)
    print()

    baseline_total = float(resolve_portfolio_baseline_usd(total))
    baseline_delta = total - baseline_total
    baseline_pct = _pct_change(total, baseline_total)
    session_total, session_started_at = resolve_session_baseline(total, reset=reset_session)
    session_delta = total - session_total
    session_pct = _pct_change(total, session_total)
    baseline_24h = resolve_24h_baseline(total)
    if baseline_24h is not None:
        pnl_24h = total - baseline_24h
        pct_24h = _pct_change(total, baseline_24h)
        pnl_24h_line = f"24h PnL:      ${pnl_24h:+.2f} ({pct_24h:+.2f}%)"
    else:
        pnl_24h_line = "24h PnL:      n/a (need >=24h history in portfolio_history.csv)"

    print("📊 PNL SNAPSHOT")
    print(f"Since baseline: ${baseline_delta:+.2f} ({baseline_pct:+.2f}%)")
    print(f"Session PnL:   ${session_delta:+.2f} ({session_pct:+.2f}%)")
    print(f"Session start: {session_started_at}")
    mark_line = format_mark_delta_est_line(session_started_at)
    if mark_line:
        print(mark_line)
    print(format_net_after_opex_line(session_delta, session_started_at))
    flow_line = format_flow_adjusted_line(session_delta, session_total, session_started_at)
    if flow_line:
        print(flow_line)
    print(pnl_24h_line)
    _print_adverse_day_oneliner(total)
    _print_velocity_block(session_started_at=session_started_at, seed_usd=total)

    win_spec = lookback if (lookback and str(lookback).strip()) else "24h"
    _print_lookback_table(total, parse_lookback_windows(win_spec))
    print()
    _print_portfolio_csv_analytics()
    return 0


_CYCLE_TS_RE = re.compile(r"=== CYCLE (\d+)")
_SWAP_SUCCESS_MARKER = "Swap executed successfully!"
_TRADE_ATTRIBUTION_ONCHAIN_RE = re.compile(
    r"\[nanoclaw\]\s+TRADE_ATTRIBUTION\s+tx=(0x[0-9a-fA-F]+).*?\bsz≈([\d.eE+\-]+)"
)


_TRADE_SKIPPED_MARKER = "TRADE SKIPPED"
_TRADE_SKIPPED_COLON_RE = re.compile(r"TRADE SKIPPED:\s*(.+?)(?:\s*—|\s*$)")
_TRADE_SKIPPED_PIPE_RE = re.compile(r"TRADE SKIPPED\s*\|\s*([^|]+)")


def _normalize_trade_skip_reason(raw: str) -> str:
    reason = raw.strip()
    if not reason:
        return "unknown"
    paren = reason.find("(")
    if paren > 0:
        reason = reason[:paren].strip()
    return reason or "unknown"


def parse_trade_skip_reason(line: str) -> str | None:
    """Extract a short reason key from a ``TRADE SKIPPED`` log line."""
    if _TRADE_SKIPPED_MARKER not in line:
        return None
    pipe_match = _TRADE_SKIPPED_PIPE_RE.search(line)
    if pipe_match:
        return _normalize_trade_skip_reason(pipe_match.group(1))
    colon_match = _TRADE_SKIPPED_COLON_RE.search(line)
    if colon_match:
        return _normalize_trade_skip_reason(colon_match.group(1))
    return "unknown"


def count_trade_skips(
    log_path: Path | str = LOG_FILE,
    *,
    since_utc: datetime | None = None,
    until_utc: datetime | None = None,
) -> int:
    """
    Count ``TRADE SKIPPED`` lines in ``real_cron.log``.

    When ``since_utc`` / ``until_utc`` are set, each skip is attributed to the
    preceding ``=== CYCLE <unix_ts>`` line (same as ``count_velocity_fills``).
    Without a window, every matching line is counted (lifetime grep semantics).
    """
    path = Path(log_path)
    if not path.is_file():
        return 0
    since_ts = since_utc.timestamp() if since_utc is not None else None
    until_ts = until_utc.timestamp() if until_utc is not None else None
    windowed = since_ts is not None or until_ts is not None
    last_ts = 0
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CYCLE_TS_RE.search(line)
        if m:
            last_ts = int(m.group(1))
            continue
        if _TRADE_SKIPPED_MARKER not in line:
            continue
        if windowed:
            if last_ts <= 0:
                continue
            if since_ts is not None and last_ts < since_ts:
                continue
            if until_ts is not None and last_ts >= until_ts:
                continue
        n += 1
    return n


def trade_skip_reason_counts(
    log_path: Path | str = LOG_FILE,
    *,
    since_utc: datetime | None = None,
    until_utc: datetime | None = None,
) -> dict[str, int]:
    """Aggregate skip reasons over an optional CYCLE-attributed UTC window."""
    path = Path(log_path)
    if not path.is_file():
        return {}
    since_ts = since_utc.timestamp() if since_utc is not None else None
    until_ts = until_utc.timestamp() if until_utc is not None else None
    windowed = since_ts is not None or until_ts is not None
    last_ts = 0
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CYCLE_TS_RE.search(line)
        if m:
            last_ts = int(m.group(1))
            continue
        reason = parse_trade_skip_reason(line)
        if reason is None:
            continue
        if windowed:
            if last_ts <= 0:
                continue
            if since_ts is not None and last_ts < since_ts:
                continue
            if until_ts is not None and last_ts >= until_ts:
                continue
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def format_trade_skip_stats(
    log_path: Path | str = LOG_FILE,
    *,
    now_utc: datetime | None = None,
    top_n: int = 3,
) -> list[str]:
    """Human-readable trade-skip counters for ``nanodaily`` TODAY STATS."""
    now = now_utc or datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    lifetime = count_trade_skips(log_path)
    last_24h = count_trade_skips(log_path, since_utc=since, until_utc=now)
    lines = [
        f"Trade skips (lifetime): {lifetime}",
        f"Trade skips (24h UTC): {last_24h}",
    ]
    reasons = trade_skip_reason_counts(log_path, since_utc=since, until_utc=now)
    if reasons:
        top = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        parts = [f"{name} ({count})" for name, count in top]
        lines.append(f"Top skip reasons (24h): {', '.join(parts)}")
    return lines


def print_trade_skip_stats() -> int:
    for line in format_trade_skip_stats():
        print(line)
    return 0


def count_velocity_fills(
    log_path: Path | str = LOG_FILE,
    *,
    since_utc: datetime | None = None,
    until_utc: datetime | None = None,
) -> int:
    """
    On-chain swap count from ``real_cron.log``.

    Each ``Swap executed successfully!`` line is attributed to the preceding
    ``=== CYCLE <unix_ts>`` line (log lines have no calendar date prefix).
    """
    path = Path(log_path)
    if not path.is_file():
        return 0
    since_ts = since_utc.timestamp() if since_utc is not None else None
    until_ts = until_utc.timestamp() if until_utc is not None else None
    last_ts = 0
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CYCLE_TS_RE.search(line)
        if m:
            last_ts = int(m.group(1))
            continue
        if _SWAP_SUCCESS_MARKER not in line:
            continue
        if last_ts <= 0:
            continue
        if since_ts is not None and last_ts < since_ts:
            continue
        if until_ts is not None and last_ts >= until_ts:
            continue
        n += 1
    return n


def sum_turnover_usd(
    log_path: Path | str = LOG_FILE,
    *,
    since_utc: datetime | None = None,
    until_utc: datetime | None = None,
) -> tuple[float, int]:
    """
    On-chain swap notional from ``real_cron.log`` TRADE_ATTRIBUTION lines with ``tx=0x…``.

    Each line is attributed to the preceding ``=== CYCLE <unix_ts>`` (same as velocity).
    Plan-only lines (``TRADE_ATTRIBUTION | Asset=…``, no ``tx=``) are ignored.
    Dedupes by tx hex per window (one notional per tx if the log repeats).
    """
    path = Path(log_path)
    if not path.is_file():
        return 0.0, 0
    since_ts = since_utc.timestamp() if since_utc is not None else None
    until_ts = until_utc.timestamp() if until_utc is not None else None
    last_ts = 0
    seen_tx: set[str] = set()
    notional_sum = 0.0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CYCLE_TS_RE.search(line)
        if m:
            last_ts = int(m.group(1))
            continue
        if "TRADE_ATTRIBUTION" not in line or "tx=0x" not in line:
            continue
        attr = _TRADE_ATTRIBUTION_ONCHAIN_RE.search(line)
        if not attr:
            continue
        if last_ts <= 0:
            continue
        if since_ts is not None and last_ts < since_ts:
            continue
        if until_ts is not None and last_ts >= until_ts:
            continue
        tx_hex = attr.group(1).lower()
        if tx_hex in seen_tx:
            continue
        seen_tx.add(tx_hex)
        try:
            sz = float(attr.group(2))
        except ValueError:
            continue
        if not math.isfinite(sz) or sz < 0:
            continue
        notional_sum += sz
    return notional_sum, len(seen_tx)


def _utc_day_window(now_utc: datetime | None = None) -> tuple[datetime, datetime]:
    now = now_utc or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _session_started_at_label() -> str | None:
    data = _read_session_baseline(Path(SESSION_BASELINE_FILE))
    if isinstance(data, dict):
        raw = str(data.get("session_started_at") or "").strip()
        return raw or None
    return None


def format_velocity_lines(
    *,
    log_path: Path | str = LOG_FILE,
    session_started_at: str | None = None,
    now_utc: datetime | None = None,
) -> list[str]:
    """Human-readable velocity: UTC calendar day + optional session (tag/deploy) window."""
    now = now_utc or datetime.now(timezone.utc)
    day_start, day_end = _utc_day_window(now)
    utc_n = count_velocity_fills(log_path, since_utc=day_start, until_utc=day_end)
    lines = [f"velocity_fills_per_day_utc={float(utc_n):.1f} (UTC {day_start.date()})"]
    sess_label = session_started_at if session_started_at is not None else _session_started_at_label()
    sess_dt = _parse_iso_ts(sess_label) if sess_label else None
    if sess_dt is not None:
        sess_n = count_velocity_fills(log_path, since_utc=sess_dt)
        lines.append(f"velocity_fills_session={float(sess_n):.1f} (since {sess_label})")
    return lines


def format_turnover_lines(
    *,
    log_path: Path | str = LOG_FILE,
    session_started_at: str | None = None,
    seed_usd: float,
    now_utc: datetime | None = None,
) -> list[str]:
    """Human-readable turnover: UTC calendar day + optional session window vs current seed TOTAL."""
    now = now_utc or datetime.now(timezone.utc)
    day_start, day_end = _utc_day_window(now)
    day_notional, _ = sum_turnover_usd(log_path, since_utc=day_start, until_utc=day_end)
    seed = float(seed_usd)
    day_mult = day_notional / seed if seed > 0 else 0.0
    lines = [
        f"turnover_notional_usd_day_utc={day_notional:.2f} | "
        f"turnover_multiple_day_utc={day_mult:.2f}x (seed=${seed:.2f})"
    ]
    sess_label = session_started_at if session_started_at is not None else _session_started_at_label()
    sess_dt = _parse_iso_ts(sess_label) if sess_label else None
    if sess_dt is not None:
        sess_notional, _ = sum_turnover_usd(log_path, since_utc=sess_dt)
        sess_mult = sess_notional / seed if seed > 0 else 0.0
        lines.append(
            f"turnover_notional_usd_session={sess_notional:.2f} | "
            f"turnover_multiple_session={sess_mult:.2f}x (seed=${seed:.2f})"
        )
    return lines


def _print_adverse_day_oneliner(current_total_usd: float) -> None:
    try:
        from nanoclaw.pnl_adverse_day import (
            compute_adverse_day_metrics,
            format_adverse_day_oneliner,
            pnl_adverse_day_enabled,
        )
    except Exception:
        return
    if not pnl_adverse_day_enabled():
        return
    try:
        metrics = compute_adverse_day_metrics(current_total_usd=float(current_total_usd))
        line = format_adverse_day_oneliner(metrics)
        if line:
            print(line)
    except Exception:
        return


def _print_velocity_block(*, session_started_at: str | None = None, seed_usd: float | None = None) -> None:
    print("📈 ROTATION")
    for line in format_velocity_lines(session_started_at=session_started_at):
        print(line)
    if seed_usd is not None:
        for line in format_turnover_lines(session_started_at=session_started_at, seed_usd=float(seed_usd)):
            print(line)
    print()


def print_velocity_only() -> int:
    bal = get_current_balance()
    seed = float(bal["total"]) if bal else 0.0
    for line in format_velocity_lines():
        print(line)
    for line in format_turnover_lines(seed_usd=seed):
        print(line)
    return 0


def get_recent_trades(n=8):
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    trades = []
    for line in reversed(lines):
        if any(kw in line for kw in ["REAL TX HASH", "Swap executed", "PROTECTION TRIGGERED", "Swap confirmed"]):
            trades.append(line.strip()[:130])
            if len(trades) >= n:
                break
    return list(reversed(trades))


def _pct_change(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


_DAYS_PER_MONTH_OPEX = 30.0


def _parse_env_usd(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except ValueError:
        return default
    if not math.isfinite(value) or value < 0.0:
        return default
    return value


def monthly_opex_usd() -> float:
    """Sum of monthly RPC/misc and hosting opex from env (USD)."""
    return _parse_env_usd("OPEX_MONTHLY_USD") + _parse_env_usd("HOSTING_MONTHLY_USD")


def prorate_opex_to_session(
    session_started_at: str,
    *,
    now_utc: datetime | None = None,
) -> tuple[float, float, float]:
    """Return ``(prorated_usd, elapsed_days, monthly_total_usd)`` for the session window."""
    monthly = monthly_opex_usd()
    if monthly <= 0.0:
        return 0.0, 0.0, 0.0
    sess_dt = _parse_iso_ts(session_started_at)
    if sess_dt is None:
        return 0.0, 0.0, monthly
    now = now_utc or datetime.now(timezone.utc)
    elapsed_seconds = max(0.0, (now - sess_dt).total_seconds())
    elapsed_days = elapsed_seconds / 86400.0
    prorated = monthly * (elapsed_days / _DAYS_PER_MONTH_OPEX)
    return prorated, elapsed_days, monthly


def compute_net_after_opex(
    session_pnl_usd: float,
    session_started_at: str,
    *,
    now_utc: datetime | None = None,
) -> dict[str, float]:
    prorated, elapsed_days, monthly = prorate_opex_to_session(
        session_started_at, now_utc=now_utc
    )
    return {
        "net_after_opex": float(session_pnl_usd) - prorated,
        "session_pnl": float(session_pnl_usd),
        "prorated_opex": prorated,
        "monthly_opex": monthly,
        "elapsed_days": elapsed_days,
    }


def format_net_after_opex_line(
    session_pnl_usd: float,
    session_started_at: str,
    *,
    now_utc: datetime | None = None,
) -> str:
    info = compute_net_after_opex(session_pnl_usd, session_started_at, now_utc=now_utc)
    if info["monthly_opex"] <= 0.0:
        return "Net after opex (est): n/a (set OPEX_MONTHLY_USD / HOSTING_MONTHLY_USD in .env)"
    return (
        f"Net after opex (est): ${info['net_after_opex']:+.2f} (session) | "
        f"opex_budget=${info['monthly_opex']:.2f}/mo prorated"
    )


def _load_fe_usd_spot_cache(path: Path | None = None) -> dict:
    p = path or Path(FE_USD_SPOT_CACHE_FILE)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _parse_fe_usd_auto_floor_updates(log_path: Path) -> list[tuple[int, str, float]]:
    if not log_path.is_file():
        return []
    out: list[tuple[int, str, float]] = []
    last_ts = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CYCLE_TS_RE.search(line)
        if m:
            last_ts = int(m.group(1))
            continue
        um = _AUTO_FLOOR_UPDATE_RE.search(line)
        if not um or last_ts <= 0:
            continue
        try:
            out.append((last_ts, um.group(1).strip(), float(um.group(2))))
        except ValueError:
            continue
    return out


def _session_start_spots_per_symbol(
    session_ts: float,
    *,
    log_path: Path | str = LOG_FILE,
    cache_path: Path | str = FE_USD_SPOT_CACHE_FILE,
) -> dict[str, float]:
    spots: dict[str, float] = {}
    for cycle_ts, sym, spot in _parse_fe_usd_auto_floor_updates(Path(log_path)):
        if cycle_ts <= session_ts and spot > 0:
            spots[sym] = spot
    cache = _load_fe_usd_spot_cache(Path(cache_path))
    for sym, entry in cache.items():
        if not isinstance(entry, dict):
            continue
        try:
            spot = float(entry.get("spot_usd"))
            updated = float(entry.get("updated_unix"))
        except (TypeError, ValueError):
            continue
        if spot > 0 and updated > 0 and updated <= session_ts:
            spots.setdefault(sym, spot)
    return spots


def max_fe_spot_cache_session_pct_move(
    session_started_at: str,
    *,
    log_path: Path | str = LOG_FILE,
    cache_path: Path | str = FE_USD_SPOT_CACHE_FILE,
) -> float:
    """Largest |spot change| / session-start spot across followed-equity cache symbols."""
    sess_dt = _parse_iso_ts(session_started_at)
    if sess_dt is None:
        return 0.0
    session_ts = sess_dt.timestamp()
    start_spots = _session_start_spots_per_symbol(
        session_ts, log_path=log_path, cache_path=cache_path
    )
    if not start_spots:
        return 0.0
    cache = _load_fe_usd_spot_cache(Path(cache_path))
    max_pct = 0.0
    for sym, start_spot in start_spots.items():
        entry = cache.get(sym)
        if not isinstance(entry, dict):
            continue
        try:
            cur_spot = float(entry.get("spot_usd"))
        except (TypeError, ValueError):
            continue
        if cur_spot > 0 and start_spot > 0:
            max_pct = max(max_pct, abs(cur_spot - start_spot) / start_spot)
    return max_pct


def _fe_usd_from_log_at_or_before(session_dt: datetime, log_path: Path) -> float | None:
    if not log_path.is_file():
        return None
    session_ts = session_dt.timestamp()
    best_ts: float | None = None
    best_fe: float | None = None
    last_cycle_ts = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CYCLE_TS_RE.search(line)
        if m:
            last_cycle_ts = int(m.group(1))
            continue
        if "WALLET TOTAL USD" not in line or "FE_USD=" not in line:
            continue
        fe_m = _FE_USD_COMPONENT_RE.search(line)
        if not fe_m:
            continue
        try:
            fe = float(fe_m.group(1))
        except ValueError:
            continue
        line_ts: float | None = None
        cal = _LOG_CAL_TS_RE.match(line)
        if cal:
            try:
                dt = datetime.strptime(cal.group(1), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                line_ts = dt.timestamp()
            except ValueError:
                line_ts = None
        elif last_cycle_ts > 0:
            line_ts = float(last_cycle_ts)
        if line_ts is None or line_ts > session_ts:
            continue
        if best_ts is None or line_ts >= best_ts:
            best_ts = line_ts
            best_fe = fe
    return best_fe


def _current_fe_usd_usd(log_path: Path) -> float | None:
    try:
        from modules import runtime

        return float(runtime.get_balances().followed_equity_usd)
    except Exception:
        pass
    if not log_path.is_file():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        if "WALLET TOTAL USD" not in line or "FE_USD=" not in line:
            continue
        fe_m = _FE_USD_COMPONENT_RE.search(line)
        if fe_m:
            try:
                return float(fe_m.group(1))
            except ValueError:
                continue
    return None


def compute_mark_delta_est(
    session_started_at: str,
    *,
    current_fe_usd: float | None = None,
    log_path: Path | str = LOG_FILE,
    cache_path: Path | str = FE_USD_SPOT_CACHE_FILE,
) -> float | None:
    """Read-only FE MTM delta estimate when spot cache moved >1% since session start."""
    pct = max_fe_spot_cache_session_pct_move(
        session_started_at, log_path=log_path, cache_path=cache_path
    )
    if pct <= _MARK_DELTA_SPOT_PCT_THRESHOLD:
        return None
    sess_dt = _parse_iso_ts(session_started_at)
    if sess_dt is None:
        return None
    lp = Path(log_path)
    start_fe = _fe_usd_from_log_at_or_before(sess_dt, lp)
    cur_fe = current_fe_usd if current_fe_usd is not None else _current_fe_usd_usd(lp)
    if start_fe is None or cur_fe is None:
        return None
    return float(cur_fe) - float(start_fe)


def format_mark_delta_est_line(
    session_started_at: str,
    *,
    current_fe_usd: float | None = None,
    log_path: Path | str = LOG_FILE,
    cache_path: Path | str = FE_USD_SPOT_CACHE_FILE,
) -> str | None:
    delta = compute_mark_delta_est(
        session_started_at,
        current_fe_usd=current_fe_usd,
        log_path=log_path,
        cache_path=cache_path,
    )
    if delta is None:
        return None
    return f"mark_delta_est: ${delta:+.2f} (FE spot cache)"


@dataclass(frozen=True)
class FlowEvent:
    """Capital flow tag (deposit/withdraw) for flow-adjusted session PnL."""

    ts: datetime
    kind: str  # deposit_est | withdraw_est | deposit | withdraw
    amount_usd: float
    source: str  # heuristic | manual
    confidence: float | None = None

    @property
    def signed_usd(self) -> float:
        if self.kind in {"deposit_est", "deposit"}:
            return float(self.amount_usd)
        return -float(self.amount_usd)


def _parse_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_env_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except ValueError:
        return default
    if not math.isfinite(value) or value <= 0.0:
        return default
    return value


def pnl_flow_tag_enabled() -> bool:
    return _parse_env_bool("PNL_FLOW_TAG_ENABLED", default=True)


def pnl_flow_step_min_usd() -> float:
    return _parse_env_positive_float("PNL_FLOW_STEP_MIN_USD", 5.0)


def pnl_flow_lookback_hours() -> float:
    return _parse_env_positive_float("PNL_FLOW_LOOKBACK_HOURS", 24.0)


def _stable_usd_from_history_row(row: dict) -> float | None:
    try:
        usdt = float(row.get("usdt", "") or 0.0)
        usdc = float(row.get("usdc", "") or 0.0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(usdt) or not math.isfinite(usdc):
        return None
    return usdt + usdc


def load_portfolio_history_rows() -> list[tuple[datetime, float, float]]:
    """Chronological ``(timestamp, total_value, stable_usd)`` from portfolio_history.csv."""
    csv_path = Path(PORTFOLIO_HISTORY_FILE)
    if not csv_path.is_file():
        return []
    out: list[tuple[datetime, float, float]] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    total = float(row.get("total_value", ""))
                except (TypeError, ValueError):
                    continue
                stable = _stable_usd_from_history_row(row)
                if stable is None or not math.isfinite(total):
                    continue
                out.append((ts, total, stable))
    except Exception:
        return []
    out.sort(key=lambda x: x[0])
    dedup: list[tuple[datetime, float, float]] = []
    for ts, total, stable in out:
        if dedup and dedup[-1][0] == ts:
            dedup[-1] = (ts, total, stable)
        else:
            dedup.append((ts, total, stable))
    return dedup


def _classify_flow_step(
    delta_total: float,
    delta_stable: float,
    *,
    min_usd: float,
    stable_ratio: float = _FLOW_STABLE_EXPLAIN_RATIO,
) -> tuple[str, float] | None:
    """Return ``(kind, confidence)`` when a TOTAL step looks like capital in/out."""
    if abs(delta_total) < min_usd:
        return None
    if delta_total == 0.0 or delta_stable == 0.0:
        return None
    if (delta_total > 0) != (delta_stable > 0):
        return None
    explain = abs(delta_stable) / abs(delta_total)
    if explain < stable_ratio:
        return None
    residual = abs(delta_total - delta_stable)
    if residual > abs(delta_total) * (1.0 - stable_ratio):
        return None
    kind = "deposit_est" if delta_total > 0 else "withdraw_est"
    confidence = min(1.0, explain)
    return kind, confidence


def detect_flow_events_heuristic(
    *,
    min_usd: float | None = None,
    lookback_hours: float | None = None,
    now_utc: datetime | None = None,
    history_rows: list[tuple[datetime, float, float]] | None = None,
) -> list[FlowEvent]:
    """Detect sudden TOTAL steps explained mostly by stable-leg change (v1 heuristic)."""
    threshold = float(min_usd if min_usd is not None else pnl_flow_step_min_usd())
    lookback = float(lookback_hours if lookback_hours is not None else pnl_flow_lookback_hours())
    now = now_utc or datetime.now(timezone.utc)
    rows = history_rows if history_rows is not None else load_portfolio_history_rows()
    if len(rows) < 2:
        return []
    cutoff = now - timedelta(hours=lookback)
    events: list[FlowEvent] = []
    for idx in range(1, len(rows)):
        ts_prev, total_prev, stable_prev = rows[idx - 1]
        ts_cur, total_cur, stable_cur = rows[idx]
        if ts_cur < cutoff:
            continue
        delta_total = total_cur - total_prev
        delta_stable = stable_cur - stable_prev
        classified = _classify_flow_step(delta_total, delta_stable, min_usd=threshold)
        if classified is None:
            continue
        kind, confidence = classified
        events.append(
            FlowEvent(
                ts=ts_cur,
                kind=kind,
                amount_usd=abs(delta_total),
                source="heuristic",
                confidence=confidence,
            )
        )
    return events


def load_manual_flow_events(path: Path | str | None = None) -> list[FlowEvent]:
    """Operator tags from ``.runtime/pnl_flow_events.jsonl`` (one JSON object per line)."""
    p = Path(path or PNL_FLOW_EVENTS_FILE)
    if not p.is_file():
        return []
    events: list[FlowEvent] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        ts_raw = obj.get("timestamp") or obj.get("ts")
        kind = str(obj.get("kind") or "").strip().lower()
        if kind not in {"deposit", "withdraw", "deposit_est", "withdraw_est"}:
            continue
        try:
            amount = float(obj.get("amount_usd"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(amount) or amount <= 0.0:
            continue
        ts = _parse_iso_ts(str(ts_raw or ""))
        if ts is None:
            continue
        events.append(
            FlowEvent(
                ts=ts,
                kind=kind,
                amount_usd=amount,
                source="manual",
                confidence=None,
            )
        )
    events.sort(key=lambda e: e.ts)
    return events


def collect_session_flow_events(
    session_started_at: str,
    *,
    min_usd: float | None = None,
    lookback_hours: float | None = None,
    now_utc: datetime | None = None,
    history_rows: list[tuple[datetime, float, float]] | None = None,
    manual_path: Path | str | None = None,
) -> list[FlowEvent]:
    """Merge heuristic + manual flow tags within the session window."""
    sess_dt = _parse_iso_ts(session_started_at)
    if sess_dt is None:
        return []
    now = now_utc or datetime.now(timezone.utc)
    heuristic = detect_flow_events_heuristic(
        min_usd=min_usd,
        lookback_hours=lookback_hours,
        now_utc=now,
        history_rows=history_rows,
    )
    manual = load_manual_flow_events(manual_path)
    merged: list[FlowEvent] = []
    for event in sorted(heuristic + manual, key=lambda e: (e.ts, e.source != "manual")):
        if event.ts < sess_dt or event.ts > now:
            continue
        merged.append(event)
    return merged


def compute_flow_adjusted_session_pnl(
    session_delta_usd: float,
    session_start_total: float,
    events: list[FlowEvent],
) -> tuple[float, float]:
    """Return ``(flow_adjusted_usd, flow_adjusted_pct)`` after removing capital flows."""
    net_flow = sum(event.signed_usd for event in events)
    adjusted = float(session_delta_usd) - net_flow
    pct = _pct_change(float(session_start_total) + adjusted, float(session_start_total))
    return adjusted, pct


def format_flow_event_tag(event: FlowEvent) -> str:
    label = "deposit" if event.kind in {"deposit_est", "deposit"} else "withdraw"
    sign = "+" if label == "deposit" else "-"
    suffix = "(manual)" if event.source == "manual" else "(est)"
    return f"{label} {sign}${event.amount_usd:.2f} @ {event.ts.isoformat()} {suffix}"


def format_flow_adjusted_line(
    session_delta_usd: float,
    session_start_total: float,
    session_started_at: str,
    *,
    now_utc: datetime | None = None,
    history_rows: list[tuple[datetime, float, float]] | None = None,
    manual_path: Path | str | None = None,
) -> str | None:
    if not pnl_flow_tag_enabled():
        return None
    events = collect_session_flow_events(
        session_started_at,
        now_utc=now_utc,
        history_rows=history_rows,
        manual_path=manual_path,
    )
    adjusted, pct = compute_flow_adjusted_session_pnl(
        session_delta_usd, session_start_total, events
    )
    flows_part = ", ".join(format_flow_event_tag(e) for e in events) if events else "none"
    return (
        f"Flow-adjusted session PnL: ${adjusted:+.2f} ({pct:+.2f}%) | "
        f"detected flows: {flows_part}"
    )


def _parse_iso_ts(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_session_baseline(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_session_baseline(path: Path, total: float, now_utc: datetime) -> dict:
    payload = {
        "session_start_total": float(total),
        "session_started_at": now_utc.isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return payload


def resolve_session_baseline(current_total: float, *, reset: bool = False) -> tuple[float, str]:
    path = Path(SESSION_BASELINE_FILE)
    now_utc = datetime.now(timezone.utc)
    if reset:
        data = _write_session_baseline(path, current_total, now_utc)
        return float(data["session_start_total"]), str(data["session_started_at"])
    existing = _read_session_baseline(path)
    if isinstance(existing, dict):
        try:
            return float(existing["session_start_total"]), str(existing["session_started_at"])
        except Exception:
            pass
    data = _write_session_baseline(path, current_total, now_utc)
    return float(data["session_start_total"]), str(data["session_started_at"])


def _resolve_history_at_or_before(cutoff_utc: datetime) -> tuple[float | None, datetime | None]:
    """Portfolio_history row: last in file order with timestamp <= cutoff (append-only CSV semantics)."""
    csv_path = Path(PORTFOLIO_HISTORY_FILE)
    if not csv_path.is_file():
        return None, None
    best_total: float | None = None
    best_ts: datetime | None = None
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    total = float(row.get("total_value", ""))
                except Exception:
                    continue
                if ts <= cutoff_utc:
                    best_ts = ts
                    best_total = total
    except Exception:
        return None, None
    if best_total is None or best_ts is None:
        return None, None
    return float(best_total), best_ts


def resolve_24h_baseline(current_total: float) -> float | None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    ref, _ts = _resolve_history_at_or_before(cutoff)
    return ref


def parse_lookback_windows(raw: str) -> list[tuple[str, float]]:
    """
    Parse comma-separated lookback specs for portfolio_history.csv (hour counts).

    Suffixes: h (hours), d (days→×24), w (weeks→×24×7), m (months→×24×30, ops approximation).
    Examples: \"24h\", \"1d\", \"2d\", \"1w\", \"2w\", \"1m\"
    """
    out: list[tuple[str, float]] = []
    if not raw or not str(raw).strip():
        return [("24h", 24.0)]
    for part in str(raw).split(","):
        token = part.strip().lower()
        if not token:
            continue
        try:
            if token.endswith("h"):
                label = token
                hours = float(token[:-1])
            elif token.endswith("d"):
                label = token
                hours = float(token[:-1]) * 24.0
            elif token.endswith("w"):
                label = token
                hours = float(token[:-1]) * 24.0 * 7.0
            elif token.endswith("m"):
                label = token
                hours = float(token[:-1]) * 24.0 * 30.0
            else:
                # Bare number = hours
                label = f"{token}h"
                hours = float(token)
        except ValueError:
            continue
        if hours <= 0 or not math.isfinite(hours):
            continue
        out.append((label, hours))
    return out if out else [("24h", 24.0)]


def load_portfolio_total_series() -> list[tuple[datetime, float]]:
    """Chronological (timestamp, total_value) from portfolio_history.csv."""
    csv_path = Path(PORTFOLIO_HISTORY_FILE)
    if not csv_path.is_file():
        return []
    out: list[tuple[datetime, float]] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    tv = float(row.get("total_value", ""))
                except Exception:
                    continue
                if not math.isfinite(tv):
                    continue
                out.append((ts, tv))
    except Exception:
        return []
    out.sort(key=lambda x: x[0])
    dedup: list[tuple[datetime, float]] = []
    for ts, tv in out:
        if dedup and dedup[-1][0] == ts:
            dedup[-1] = (ts, tv)
        else:
            dedup.append((ts, tv))
    return dedup


_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def render_ascii_sparkline(values: list[float], width: int = 64) -> str:
    """Single-row Unicode height chart (no external deps)."""
    if not values:
        return ""
    w = max(8, min(120, int(width)))
    pts = list(values)
    if len(pts) == 1:
        c = _SPARK_BLOCKS[len(_SPARK_BLOCKS) // 2]
        return c * w
    if len(pts) < w:
        stretched: list[float] = []
        for i in range(w):
            t = i / (w - 1)
            idx = min(int(t * (len(pts) - 1) + 0.5), len(pts) - 1)
            stretched.append(pts[idx])
        pts = stretched
    elif len(pts) > w:
        step = len(pts) / w
        sampled = []
        for i in range(w):
            idx = min(int((i + 0.5) * step), len(pts) - 1)
            sampled.append(pts[idx])
        pts = sampled
    lo, hi = min(pts), max(pts)
    if hi <= lo:
        c = _SPARK_BLOCKS[len(_SPARK_BLOCKS) // 2]
        return c * len(pts)
    chars: list[str] = []
    for v in pts:
        t = (v - lo) / (hi - lo)
        idx = int(t * (len(_SPARK_BLOCKS) - 1) + 0.5)
        idx = max(0, min(len(_SPARK_BLOCKS) - 1, idx))
        chars.append(_SPARK_BLOCKS[idx])
    return "".join(chars)


def _hourly_last_close_rows(series: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """One row per UTC hour: last total_value in that hour."""
    buckets: dict[datetime, float] = {}
    for ts, tv in series:
        hour = ts.replace(minute=0, second=0, microsecond=0)
        buckets[hour] = tv
    return sorted(buckets.items(), key=lambda x: x[0])


def _print_portfolio_csv_analytics(*, chart_width: int = 72, hourly_rows: int = 24) -> None:
    """ASCII trend + hourly closes from portfolio_history (decision support, not accounting-grade)."""
    series = load_portfolio_total_series()
    if len(series) < 2:
        print("📈 TREND (portfolio_history.csv): need ≥2 rows for chart/hourly stats")
        return

    values = [tv for _ts, tv in series]
    spark = render_ascii_sparkline(values, width=chart_width)
    lo_v, hi_v = min(values), max(values)
    first_t, last_t = series[0][0], series[-1][0]
    print("📈 TREND — bot TOTAL ($) from portfolio_history.csv (ups/downs; deposits = steps)")
    print(f"   {spark}")
    print(
        f"   span {first_t.isoformat()} → {last_t.isoformat()}  |  "
        f"range ${lo_v:.2f} … ${hi_v:.2f}  |  {len(values)} snapshots"
    )

    hourly = _hourly_last_close_rows(series)
    if len(hourly) < 2:
        return

    tail = hourly[-max(2, int(hourly_rows) + 1) :]
    print()
    print(f"🕐 HOURLY (UTC, last {min(hourly_rows, len(tail) - 1)} completed hour-boundaries)")
    print("   hour_start (UTC)     close USD    Δ vs prev hr")
    deltas: list[float] = []
    prev: float | None = None
    rows_shown = 0
    for hour, clo in tail:
        if prev is None:
            prev = clo
            continue
        d = clo - prev
        deltas.append(d)
        if rows_shown < hourly_rows:
            print(f"   {hour.isoformat()}   ${clo:8.2f}   ${d:+8.2f}")
        prev = clo
        rows_shown += 1

    if deltas:
        net = sum(deltas)
        avg = net / len(deltas)
        ups = sum(1 for x in deltas if x > 0.01)
        downs = sum(1 for x in deltas if x < -0.01)
        print(
            f"   — over printed window: net ${net:+.2f}  |  avg hr Δ ${avg:+.2f}  |  "
            f"up {ups} / down {downs} (hours)"
        )


def _print_lookback_table(current_total: float, windows: list[tuple[str, float]]) -> None:
    now_utc = datetime.now(timezone.utc)
    print("📅 LOOKBACK (portfolio_history.csv — bot TOTAL at snapshot time)")
    print(
        "   Deposits/top-ups show as sudden steps up; same for large withdrawals "
        "(see Flow-adjusted session PnL in nanodaily when PNL_FLOW_TAG_ENABLED=true)."
    )
    for label, hours in windows:
        cutoff = now_utc - timedelta(hours=hours)
        ref, ref_ts = _resolve_history_at_or_before(cutoff)
        if ref is None or ref_ts is None:
            print(f"   {label:>5}  n/a (no CSV row at or before {cutoff.isoformat()} — need longer history)")
            continue
        delta = current_total - ref
        pct = _pct_change(current_total, ref)
        print(
            f"   {label:>5}  ref ${ref:.2f} @ {ref_ts.isoformat()}  |  "
            f"Δ vs now ${delta:+.2f} ({pct:+.2f}%)"
        )


def print_report(*, reset_session: bool = False) -> int:
    bal = get_current_balance()

    print("═══════════════════════════════════════════════")
    print("           NANOC LAW PnL REPORT (FIXED v4)")
    print("═══════════════════════════════════════════════")

    if not bal:
        print("No valid balance found.")
        print()
        print("📈 RECENT TRADES (last 8)")
        print("═══════════════════════════════════════════════")
        for t in get_recent_trades():
            print(t)
        print("═══════════════════════════════════════════════")
        return 0

    total = float(bal["total"])
    _print_balance_block(bal)
    print()

    baseline_total = float(resolve_portfolio_baseline_usd(total))
    baseline_delta = total - baseline_total
    baseline_pct = _pct_change(total, baseline_total)

    session_total, session_started_at = resolve_session_baseline(total, reset=reset_session)
    session_delta = total - session_total
    session_pct = _pct_change(total, session_total)

    baseline_24h = resolve_24h_baseline(total)
    if baseline_24h is not None:
        pnl_24h = total - baseline_24h
        pct_24h = _pct_change(total, baseline_24h)
        pnl_24h_line = f"24h PnL:      ${pnl_24h:+.2f} ({pct_24h:+.2f}%)"
    else:
        pnl_24h_line = "24h PnL:      n/a (need >=24h history in portfolio_history.csv)"

    print("📊 PNL SNAPSHOT")
    print(f"Since baseline: ${baseline_delta:+.2f} ({baseline_pct:+.2f}%)")
    print(f"Session PnL:   ${session_delta:+.2f} ({session_pct:+.2f}%)")
    print(f"Session start: {session_started_at}")
    mark_line = format_mark_delta_est_line(session_started_at)
    if mark_line:
        print(mark_line)
    print(format_net_after_opex_line(session_delta, session_started_at))
    flow_line = format_flow_adjusted_line(session_delta, session_total, session_started_at)
    if flow_line:
        print(flow_line)
    print(pnl_24h_line)
    _print_velocity_block(session_started_at=session_started_at, seed_usd=total)
    print("Reset session baseline: nanopnl --reset-session")
    print()

    recent = get_recent_trades()
    print("📈 RECENT TRADES (last 8)")
    print("═══════════════════════════════════════════════")
    for t in recent:
        print(t)
    print("═══════════════════════════════════════════════")
    if recent:
        print(f"🧾 LAST TRADE HINT: {recent[-1]}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nanoclaw PnL report")
    parser.add_argument("--reset-session", action="store_true", help="Reset session baseline to current total")
    parser.add_argument(
        "--velocity-only",
        action="store_true",
        help="Print UTC-day and session fill counts + turnover (nanovel)",
    )
    parser.add_argument(
        "--daily-summary",
        action="store_true",
        help="Compact balance + PnL + lookback + CSV trend/hourly table (for nanodaily)",
    )
    parser.add_argument(
        "--lookback",
        metavar="SPECS",
        default="",
        help=(
            "Comma-separated horizons from portfolio_history.csv: "
            "1h,4h,12h,24h,1d,2d,1w,2w,1m (d=24h, w=7d, m≈30d). "
            "Default for --daily-summary is 24h; omit to use default."
        ),
    )
    parser.add_argument(
        "--trade-skip-stats",
        action="store_true",
        help="Print lifetime and 24h UTC TRADE SKIPPED counters (for nanodaily)",
    )
    parser.add_argument(
        "--adverse-day",
        action="store_true",
        help="Print adverse-window mark/churn/fill metrics (read-only)",
    )
    return parser


def print_adverse_day_report() -> int:
    from nanoclaw.pnl_adverse_day import build_adverse_day_report

    _metrics, lines = build_adverse_day_report()
    for line in lines:
        print(line)
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    if bool(getattr(args, "adverse_day", False)):
        return print_adverse_day_report()
    if bool(args.trade_skip_stats):
        return print_trade_skip_stats()
    if bool(args.velocity_only):
        return print_velocity_only()
    lookback_arg = str(getattr(args, "lookback", "") or "").strip()
    if bool(args.daily_summary):
        lb = lookback_arg if lookback_arg else None
        return print_daily_summary(reset_session=bool(args.reset_session), lookback=lb)
    return print_report(reset_session=bool(args.reset_session))


if __name__ == "__main__":
    raise SystemExit(main())
