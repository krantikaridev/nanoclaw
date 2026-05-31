"""Operating-reserve seed from env and optional portfolio_history EMA."""

from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import config as cfg

PORTFOLIO_HISTORY_FILE = "portfolio_history.csv"
_STAGE_SEED_EMA_LOG_STATE = Path(".runtime/stage_seed_ema_log.json")
_STAGE_SEED_EMA_LOG_PREFIX = "[nanoclaw] STAGE_SEED_EMA"


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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_portfolio_total_series(
    csv_path: Path | str | None = None,
) -> list[tuple[datetime, float]]:
    """Chronological ``(timestamp, total_value)`` from portfolio_history.csv."""
    path = Path(csv_path or PORTFOLIO_HISTORY_FILE)
    if not path.is_file():
        return []
    out: list[tuple[datetime, float]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                try:
                    total = float(row.get("total_value", ""))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(total):
                    continue
                out.append((ts, total))
    except OSError:
        return []
    out.sort(key=lambda x: x[0])
    dedup: list[tuple[datetime, float]] = []
    for ts, total in out:
        if dedup and dedup[-1][0] == ts:
            dedup[-1] = (ts, total)
        else:
            dedup.append((ts, total))
    return dedup


def daily_close_series(
    series: list[tuple[datetime, float]],
) -> list[tuple[date, float]]:
    """One row per UTC calendar day: last total_value in that day."""
    buckets: dict[date, float] = {}
    for ts, total in series:
        buckets[ts.date()] = total
    return sorted(buckets.items(), key=lambda x: x[0])


def compute_ema(values: list[float], period: int) -> float | None:
    """Standard EMA over ``values`` with ``period`` lookback smoothing."""
    if not values or period <= 0:
        return None
    cleaned = [float(v) for v in values if math.isfinite(float(v))]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    alpha = 2.0 / (float(period) + 1.0)
    ema = cleaned[0]
    for value in cleaned[1:]:
        ema = alpha * value + (1.0 - alpha) * ema
    return ema


def compute_portfolio_total_ema(
    *,
    ema_days: int | None = None,
    csv_path: Path | str | None = None,
    series: list[tuple[datetime, float]] | None = None,
) -> float | None:
    """7d (configurable) EMA of daily TOTAL closes from portfolio history."""
    period = int(ema_days if ema_days is not None else getattr(cfg, "STAGE_SEED_AUTO_SYNC_EMA_DAYS", 7))
    if period <= 0:
        return None
    raw_series = series if series is not None else load_portfolio_total_series(csv_path)
    daily = daily_close_series(raw_series)
    if not daily:
        return None
    closes = [total for _day, total in daily]
    return compute_ema(closes, period)


def _read_last_ema_log_date(state_path: Path | None = None) -> str | None:
    path = state_path or _STAGE_SEED_EMA_LOG_STATE
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    logged = str(raw.get("last_log_date") or "").strip()
    return logged or None


def _write_last_ema_log_date(day_iso: str, *, state_path: Path | None = None) -> None:
    path = state_path or _STAGE_SEED_EMA_LOG_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_log_date": day_iso}) + "\n", encoding="utf-8")


def maybe_log_stage_seed_ema_once_daily(
    *,
    seed_usd: float,
    reserve_floor_usd: float,
    now_utc: datetime | None = None,
    state_path: Path | None = None,
) -> bool:
    """Print ``STAGE_SEED_EMA`` at most once per UTC day; return True if logged."""
    now = now_utc or datetime.now(timezone.utc)
    today = now.date().isoformat()
    if _read_last_ema_log_date(state_path) == today:
        return False
    print(
        f"{_STAGE_SEED_EMA_LOG_PREFIX} | seed_usd={float(seed_usd):.2f} | "
        f"reserve_floor={float(reserve_floor_usd):.2f}"
    )
    _write_last_ema_log_date(today, state_path=state_path)
    return True


def resolve_operating_reserve_seed_usd(
    live_total_usd: float,
    *,
    explicit_seed_usd: float | None = None,
    auto_sync_enabled: bool | None = None,
    ema_days: int | None = None,
    min_usd: float | None = None,
    reserve_pct: float | None = None,
    csv_path: Path | str | None = None,
    now_utc: datetime | None = None,
    log_state_path: Path | None = None,
) -> float:
    """Effective operating-reserve seed (env floor + optional portfolio EMA)."""
    explicit = float(
        explicit_seed_usd
        if explicit_seed_usd is not None
        else getattr(cfg, "STAGE_SEED_USD", 0.0) or 0.0
    )
    auto_sync = bool(
        auto_sync_enabled
        if auto_sync_enabled is not None
        else getattr(cfg, "STAGE_SEED_AUTO_SYNC_ENABLED", False)
    )
    pct = float(
        reserve_pct if reserve_pct is not None else getattr(cfg, "OPERATING_RESERVE_PCT", 10.0)
    )

    if not auto_sync:
        if explicit > 0.0:
            return explicit
        return max(float(live_total_usd), 0.0)

    ema_raw = compute_portfolio_total_ema(
        ema_days=ema_days,
        csv_path=csv_path,
    )
    floor_min = float(
        min_usd if min_usd is not None else getattr(cfg, "STAGE_SEED_AUTO_SYNC_MIN_USD", 50.0)
    )

    if ema_raw is None or not math.isfinite(ema_raw):
        seed = explicit if explicit > 0.0 else max(float(live_total_usd), 0.0)
    else:
        ema_adj = max(float(ema_raw), floor_min)
        if explicit > 0.0:
            seed = max(explicit, ema_adj)
        else:
            seed = max(ema_adj, max(float(live_total_usd), 0.0))

    maybe_log_stage_seed_ema_once_daily(
        seed_usd=seed,
        reserve_floor_usd=seed * (pct / 100.0),
        now_utc=now_utc,
        state_path=log_state_path,
    )
    return seed
