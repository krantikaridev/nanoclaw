"""Read-only adverse-window PnL attribution (mark vs churn vs trade est).

v1: ``portfolio_history.csv`` TOTAL delta + ``real_cron.log`` EXEC SUCCESS fills,
TRADE_ATTRIBUTION turnover, FE_USD log scrape for mark delta. Does not change trading.
"""

from __future__ import annotations

import csv as _csv
from dataclasses import dataclass
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
# Round-trip friction estimate on turnover (v1 manual gas + bps slippage; v2 from receipts).
_CHURN_SLIPPAGE_BPS = 10.0

_EXEC_SUCCESS_MARKER = "EXEC SUCCESS"
_CYCLE_TS_RE = re.compile(r"=== CYCLE (\d+)")
_FE_USD_COMPONENT_RE = re.compile(r"FE_USD=\$?([\d.]+)")
_WALLET_TOTAL_FE_RE = re.compile(
    r"WALLET TOTAL USD\s*\|\s*TOTAL=\$?[\d.]+.*?FE_USD=\$?([\d.]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AdverseDayMetrics:
    window_hours: float
    total_delta_usd: float
    mark_delta_usd: float
    turnover_usd: float
    fill_count: int
    gas_est_usd: float
    realized_trade_est_usd: float
    churn_cost_est_usd: float
    is_adverse: bool
    ref_total_usd: float | None
    current_total_usd: float


def _parse_env_bool(name: str, default: bool) -> bool:
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


def _parse_env_non_negative_float(name: str, default: float) -> float:
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


def pnl_adverse_day_enabled() -> bool:
    return _parse_env_bool("PNL_ADVERSE_DAY_ENABLED", default=True)


def pnl_adverse_day_window_hours() -> float:
    return _parse_env_positive_float("PNL_ADVERSE_DAY_WINDOW_HOURS", 24.0)


def pnl_adverse_day_min_fills() -> int:
    return max(0, int(_parse_env_non_negative_float("PNL_ADVERSE_DAY_MIN_FILLS", 3.0)))


def gas_usd_est_per_fill() -> float:
    return _parse_env_non_negative_float("GAS_USD_EST_PER_FILL", 0.05)


def count_exec_success_fills(
    log_path: Path | str,
    *,
    since_utc: datetime | None = None,
    until_utc: datetime | None = None,
) -> int:
    """On-chain fill count from ``EXEC SUCCESS`` lines (cycle-attributed like velocity)."""
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
        if _EXEC_SUCCESS_MARKER not in line:
            continue
        if last_ts <= 0:
            continue
        if since_ts is not None and last_ts < since_ts:
            continue
        if until_ts is not None and last_ts >= until_ts:
            continue
        n += 1
    return n


def _fe_usd_samples_in_window(
    log_path: Path,
    *,
    since_utc: datetime,
    until_utc: datetime,
) -> list[tuple[float, float]]:
    """``(line_ts, fe_usd)`` for WALLET TOTAL USD lines with FE_USD in the window."""
    if not log_path.is_file():
        return []
    since_ts = since_utc.timestamp()
    until_ts = until_utc.timestamp()
    samples: list[tuple[float, float]] = []
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
        if last_cycle_ts > 0:
            line_ts = float(last_cycle_ts)
        if line_ts is None or line_ts < since_ts or line_ts >= until_ts:
            continue
        if fe >= 0 and math.isfinite(fe):
            samples.append((line_ts, fe))
    return samples


def compute_mark_delta_usd_window(
    *,
    since_utc: datetime,
    until_utc: datetime,
    log_path: Path | str,
) -> float:
    """FE_USD change over the window (log scrape + pnl_report helpers)."""
    from scripts import pnl_report as pr

    lp = Path(log_path)

    start_fe = pr._fe_usd_from_log_at_or_before(since_utc, lp)  # noqa: SLF001
    samples = _fe_usd_samples_in_window(lp, since_utc=since_utc, until_utc=until_utc)
    end_fe: float | None = None
    if samples:
        end_fe = samples[-1][1]
    if end_fe is None:
        end_fe = pr._current_fe_usd_usd(lp)  # noqa: SLF001
    if start_fe is None and samples:
        start_fe = samples[0][1]
    if start_fe is None or end_fe is None:
        return 0.0
    return float(end_fe) - float(start_fe)


def compute_churn_cost_est_usd(*, fill_count: int, turnover_usd: float) -> tuple[float, float]:
    """Return ``(gas_est_usd, churn_cost_est_usd)`` (gas + slippage bps on turnover)."""
    gas = float(fill_count) * gas_usd_est_per_fill()
    slippage = float(turnover_usd) * (_CHURN_SLIPPAGE_BPS / 10_000.0)
    churn = gas + slippage
    return gas, churn


def _load_total_series(csv_path: Path) -> list[tuple[datetime, float]]:
    """Chronological (timestamp, total_value) from a single CSV path."""
    from scripts.pnl_report import _parse_iso_ts  # noqa: PLC0415

    if not csv_path.is_file():
        return []
    out: list[tuple[datetime, float]] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = _csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    tv = float(row.get("total_value", ""))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(tv):
                    out.append((ts, tv))
    except Exception:
        return []
    out.sort(key=lambda x: x[0])
    return out


def _resolve_total_at_or_before(cutoff_utc: datetime, csv_path: Path) -> float | None:
    """Last ``total_value`` in CSV with timestamp <= cutoff (append-only semantics)."""
    if not csv_path.is_file():
        return None
    from scripts.pnl_report import _parse_iso_ts  # noqa: PLC0415

    best: float | None = None
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = _csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    total = float(row.get("total_value", ""))
                except (TypeError, ValueError):
                    continue
                if ts <= cutoff_utc:
                    best = total
    except Exception:
        return None
    return best


def compute_adverse_day_metrics(
    *,
    current_total_usd: float,
    window_hours: float | None = None,
    log_path: Path | str = "real_cron.log",
    portfolio_history_path: Path | str = "portfolio_history.csv",
    now_utc: datetime | None = None,
) -> AdverseDayMetrics:
    from scripts import pnl_report

    hours = float(window_hours if window_hours is not None else pnl_adverse_day_window_hours())
    now = now_utc or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    csv_path = Path(portfolio_history_path)
    ref = _resolve_total_at_or_before(since, csv_path)
    if ref is None:
        series = _load_total_series(csv_path)
        if series:
            ref = float(series[0][1])
        else:
            ref = float(current_total_usd)
    total_delta = float(current_total_usd) - float(ref)
    turnover, _tx_n = pnl_report.sum_turnover_usd(
        log_path, since_utc=since, until_utc=now
    )
    fills = count_exec_success_fills(log_path, since_utc=since, until_utc=now)
    gas_est, churn_est = compute_churn_cost_est_usd(fill_count=fills, turnover_usd=turnover)
    mark_delta = compute_mark_delta_usd_window(since_utc=since, until_utc=now, log_path=log_path)
    realized = total_delta - mark_delta + churn_est
    return AdverseDayMetrics(
        window_hours=hours,
        total_delta_usd=total_delta,
        mark_delta_usd=mark_delta,
        turnover_usd=float(turnover),
        fill_count=fills,
        gas_est_usd=gas_est,
        realized_trade_est_usd=realized,
        churn_cost_est_usd=churn_est,
        is_adverse=total_delta < 0.0,
        ref_total_usd=float(ref),
        current_total_usd=float(current_total_usd),
    )


def format_adverse_day_detail_lines(metrics: AdverseDayMetrics) -> list[str]:
    if not metrics.is_adverse:
        return [
            f"Adverse window ({metrics.window_hours:g}h): n/a "
            f"(TOTAL delta ${metrics.total_delta_usd:+.2f} >= 0)"
        ]
    return [
        f"Adverse window ({metrics.window_hours:g}h): total delta=${metrics.total_delta_usd:+.2f} "
        f"(ref ${metrics.ref_total_usd:.2f} → now ${metrics.current_total_usd:.2f})",
        f"  mark_delta_usd={metrics.mark_delta_usd:+.2f}",
        f"  turnover_usd={metrics.turnover_usd:.2f}",
        f"  fill_count={metrics.fill_count}",
        f"  gas_est_usd={metrics.gas_est_usd:.2f}",
        f"  realized_trade_est_usd={metrics.realized_trade_est_usd:+.2f}",
        f"  churn_cost_est_usd={metrics.churn_cost_est_usd:.2f}",
    ]


def format_adverse_day_oneliner(metrics: AdverseDayMetrics) -> str | None:
    """Compact line for ``nanodaily`` when the window is red and fills meet the floor."""
    if not pnl_adverse_day_enabled():
        return None
    if not metrics.is_adverse:
        return None
    if metrics.fill_count < pnl_adverse_day_min_fills():
        return None
    return (
        f"Adverse window: mark ${metrics.mark_delta_usd:+.2f} | "
        f"churn est ${metrics.churn_cost_est_usd:.2f} | fills {metrics.fill_count}"
    )


def build_adverse_day_report(
    *,
    current_total_usd: float | None = None,
    window_hours: float | None = None,
    log_path: Path | str = "real_cron.log",
    portfolio_history_path: Path | str = "portfolio_history.csv",
    now_utc: datetime | None = None,
) -> tuple[AdverseDayMetrics | None, list[str]]:
    if not pnl_adverse_day_enabled():
        return None, ["PNL adverse-day metrics disabled (PNL_ADVERSE_DAY_ENABLED=false)"]
    from scripts import pnl_report

    total = current_total_usd
    if total is None:
        bal = pnl_report.get_current_balance()
        if not bal:
            return None, ["Adverse window: n/a (no current balance)"]
        total = float(bal["total"])
    metrics = compute_adverse_day_metrics(
        current_total_usd=float(total),
        window_hours=window_hours,
        log_path=log_path,
        portfolio_history_path=portfolio_history_path,
        now_utc=now_utc,
    )
    return metrics, format_adverse_day_detail_lines(metrics)
