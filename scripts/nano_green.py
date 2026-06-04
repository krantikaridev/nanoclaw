#!/usr/bin/env python3
"""Portfolio-driven green gate — configurable window (8h/12h/24h/48h).

Replaces manual ``control.json`` unpause decisions when ``EXTERNAL_AUTO_PAUSE_ENABLED=true``.

Checks:
  1. Hard unpause readiness (loss-cut off, FE runway, blocklist, copy audit)
  2. Session PnL vs floor (default -1%% — not strict breakeven)
  3. Window PnL from ``portfolio_history.csv`` over ``--hours`` (optional if no history)
  4. Pause discipline (no EXEC SUCCESS after last pause marker — always enforced when marker exists)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pnl_report import (  # noqa: E402
    get_current_balance,
    resolve_session_baseline,
)
from scripts.unpause_readiness import run_checks as run_readiness_checks  # noqa: E402

LOG_FILE = "real_cron.log"
CONTROL_FILE = "control.json"
PAUSE_LINE_RE = re.compile(r"\[CONTROL\]\s+paused=True", re.IGNORECASE)
EXEC_SUCCESS_RE = re.compile(r"EXEC SUCCESS")
FE_RUNWAY_RE = re.compile(r"FE STABLE RUNWAY")
_DERISK_EVALUATE_RE = re.compile(r"FE STABLE RUNWAY DERISK \| evaluate")
_DERISK_EXEC_PLAN_RE = re.compile(r"FE STABLE RUNWAY DERISK \| exec plan")
_LOG_CAL_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s")
_LOG_BRACKET_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
_CYCLE_TS_RE = re.compile(r"=== CYCLE (\d+)")
WALLET_TOTAL_RE = re.compile(
    r"WALLET TOTAL USD\s*\|\s*TOTAL=\$?([\d.]+).*?\|\s*FE_USD=\$?([\d.]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GreenGateResult:
    hours: float
    session_min_pct: float
    window_min_pct: float
    overall_pass: bool
    readiness_pass: bool
    session_pass: bool
    window_pass: bool
    pause_pass: bool
    lines: tuple[str, ...]
    rotation_open: tuple[str, ...]

    def trading_allowed(self) -> bool:
        return self.overall_pass and self.readiness_pass


def _read_env(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    path = root / ".env"
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _env_float(raw: str | None, default: float) -> float:
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _load_blocklist(root: Path) -> set[str]:
    path = root / ".xsignal_blocked_symbols"
    if not path.is_file():
        return set()
    return {
        ln.strip().upper()
        for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }


def _load_followed_symbols(root: Path) -> list[str]:
    path = root / "followed_equities.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    assets = data.get("assets") if isinstance(data, dict) else None
    if not isinstance(assets, list):
        return []
    out: list[str] = []
    for row in assets:
        if isinstance(row, dict):
            sym = str(row.get("symbol", "")).strip().upper()
            if sym:
                out.append(sym)
    return out


def rotation_open_symbols(root: Path) -> list[str]:
    blocked = _load_blocklist(root)
    return [s for s in _load_followed_symbols(root) if s not in blocked]


def _read_log_lines(root: Path) -> list[str]:
    path = root / LOG_FILE
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _load_control(root: Path) -> dict:
    path = root / CONTROL_FILE
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _readiness_pass(root: Path) -> tuple[bool, str]:
    results = run_readiness_checks(root)
    hard = [r for r in results if r.severity == "hard"]
    ok = all(r.passed for r in hard)
    fails = [r.name for r in hard if not r.passed]
    detail = "PASS" if ok else f"FAIL ({', '.join(fails)})"
    return ok, detail


def _session_pnl_check(
    root: Path, *, session_min_pct: float
) -> tuple[bool, str, float | None, float | None]:
    bal = get_current_balance()
    if not bal:
        return False, "FAIL | no balance", None, None
    total = float(bal["total"])
    session_total, session_started_at = resolve_session_baseline(total, reset=False)
    session_delta = total - session_total
    session_pct = (session_delta / session_total * 100.0) if session_total else 0.0
    ok = session_pct + 1e-9 >= float(session_min_pct)
    tag = "PASS" if ok else "FAIL"
    detail = (
        f"{tag} | Session PnL ${session_delta:+.2f} ({session_pct:+.2f}%) "
        f"floor={session_min_pct:+.2f}% (seed ${session_total:.2f} @ {session_started_at})"
    )
    return ok, detail, session_pct, total


def _window_pnl_check(
    root: Path,
    *,
    hours: float,
    window_min_pct: float,
    current_total: float | None,
) -> tuple[bool, str]:
    from scripts.pnl_report import _resolve_history_at_or_before  # noqa: WPS433

    if current_total is None:
        return False, "FAIL | no current TOTAL for window compare"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(hours))
    ref, ref_ts = _resolve_history_at_or_before(cutoff)
    if ref is None or ref_ts is None:
        return True, (
            f"SKIP | no portfolio_history row at or before {cutoff.isoformat()} "
            f"(need ~{hours:.0f}h of snapshots — window gate waived)"
        )

    delta = current_total - float(ref)
    pct = (delta / float(ref) * 100.0) if ref else 0.0
    ok = pct + 1e-9 >= float(window_min_pct)
    tag = "PASS" if ok else "FAIL"
    detail = (
        f"{tag} | {hours:.0f}h window PnL ${delta:+.2f} ({pct:+.2f}%) "
        f"floor={window_min_pct:+.2f}% (ref ${ref:.2f} @ {ref_ts.isoformat()})"
    )
    return ok, detail


def _pause_exec_check(root: Path, paused: bool) -> tuple[bool, str]:
    """Fail when any EXEC SUCCESS appears after the last pause marker in the log.

    Discipline is checked whenever a pause marker exists — not only while
    ``control.json`` still says ``paused=true``. That closes a gap where
    ``auto_unpause`` could leave ``paused=false`` while fills after the marker
    were ignored, allowing repeated entry trades before re-pause.
    """
    lines = _read_log_lines(root)

    last_pause_idx = None
    for idx, line in enumerate(lines):
        if PAUSE_LINE_RE.search(line):
            last_pause_idx = idx

    if last_pause_idx is None:
        if paused:
            return False, "FAIL | paused=true but no [CONTROL] paused=True in log"
        return True, "PASS | no pause marker in log"

    post_pause = lines[last_pause_idx + 1 :]
    violations = [line for line in post_pause if EXEC_SUCCESS_RE.search(line)]
    if violations:
        sample = violations[0].strip()[:120]
        return False, f"FAIL | {len(violations)} EXEC SUCCESS after pause | first={sample!r}"

    if paused:
        return True, "PASS | paused=true, no EXEC SUCCESS after pause marker"
    return True, "PASS | no EXEC SUCCESS after last pause marker"


def _fe_share_line(root: Path) -> str:
    try:
        from modules import runtime

        balances = runtime.get_balances()
        total = float(runtime.compute_authoritative_total_usd(balances))
        fe_usd = float(balances.followed_equity_usd)
        if total > 0:
            return f"fe_share={fe_usd / total:.1%} (FE_USD=${fe_usd:.2f} / TOTAL=${total:.2f})"
    except Exception:
        pass
    for line in reversed(_read_log_lines(root)):
        match = WALLET_TOTAL_RE.search(line)
        if match:
            total = float(match.group(1))
            fe_usd = float(match.group(2))
            if total > 0:
                return f"fe_share={fe_usd / total:.1%} (FE_USD=${fe_usd:.2f} / TOTAL=${total:.2f}, log)"
    return "fe_share: n/a"


def _parse_log_line_timestamp(line: str) -> datetime | None:
    cal = _LOG_CAL_TS_RE.match(line)
    if cal:
        try:
            return datetime.strptime(cal.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    bracket = _LOG_BRACKET_TS_RE.match(line)
    if bracket:
        try:
            return datetime.strptime(bracket.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _annotate_runway_line(content: str) -> str:
    """Tag DERISK probe vs swap-plan lines for operator runway tail."""
    if _DERISK_EVALUATE_RE.search(content) or (
        "FE STABLE RUNWAY DERISK" in content
        and "dynamic_trim_usd=" in content
        and "sym=" not in content
        and "exec plan" not in content
    ):
        return f"[evaluate] {content}"
    if _DERISK_EXEC_PLAN_RE.search(content) or (
        "FE STABLE RUNWAY DERISK" in content and "sym=" in content and "sell_fraction=" in content
    ):
        return f"[exec-plan] {content}"
    return content


def _runway_lines(
    root: Path,
    *,
    hours: float = 12.0,
    n: int = 3,
    now: datetime | None = None,
) -> list[str]:
    """Last ``n`` FE STABLE RUNWAY lines within ``hours`` lookback, with log timestamps."""
    now_dt = now or datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(hours=float(hours))
    matches: list[str] = []
    last_ts: datetime | None = None

    for line in _read_log_lines(root):
        cycle_m = _CYCLE_TS_RE.search(line)
        if cycle_m:
            last_ts = datetime.fromtimestamp(int(cycle_m.group(1)), tz=timezone.utc)

        explicit = _parse_log_line_timestamp(line)
        if explicit is not None:
            last_ts = explicit

        if not FE_RUNWAY_RE.search(line):
            continue

        if float(hours) > 0 and (last_ts is None or last_ts < cutoff):
            continue

        content = line.strip()
        if last_ts is not None:
            ts_prefix = last_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
            matches.append(f"{ts_prefix} | {_annotate_runway_line(content)}")
        else:
            matches.append(_annotate_runway_line(content))

    return matches[-n:]


def evaluate_green_gate(
    root: Path | None = None,
    *,
    hours: float = 12.0,
    session_min_pct: float = -1.0,
    window_min_pct: float = -2.0,
) -> GreenGateResult:
    root = root or Path(os.environ.get("NANOCLAW_ROOT", str(ROOT)))
    readiness_ok, readiness_detail = _readiness_pass(root)
    session_ok, session_detail, _, current_total = _session_pnl_check(
        root, session_min_pct=session_min_pct
    )
    window_ok, window_detail = _window_pnl_check(
        root,
        hours=hours,
        window_min_pct=window_min_pct,
        current_total=current_total,
    )
    control = _load_control(root)
    paused = bool(control.get("paused"))
    pause_ok, pause_detail = _pause_exec_check(root, paused)

    # Window SKIP (insufficient history) does not fail overall.
    window_counts = window_detail.startswith("PASS") or window_detail.startswith("SKIP")
    overall = readiness_ok and session_ok and window_counts and pause_ok

    rotation = tuple(rotation_open_symbols(root))
    lines = (
        f"readiness:  {readiness_detail}",
        f"session:    {session_detail}",
        f"window:     {window_detail}",
        f"pause_exec: {pause_detail}",
        f"rotation:   open={', '.join(rotation) or 'none'} (blocked list in .xsignal_blocked_symbols)",
        f"fe_share:   {_fe_share_line(root)}",
    )
    return GreenGateResult(
        hours=float(hours),
        session_min_pct=float(session_min_pct),
        window_min_pct=float(window_min_pct),
        overall_pass=overall,
        readiness_pass=readiness_ok,
        session_pass=session_ok,
        window_pass=window_ok or window_detail.startswith("SKIP"),
        pause_pass=pause_ok,
        lines=lines,
        rotation_open=rotation,
    )


def format_report(result: GreenGateResult, *, paused: bool, reason: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"=== nanogreen | {now} UTC | window={result.hours:.0f}h ==="
    out = [
        header,
        "",
        f"control: paused={paused} reason={reason!r}",
        "",
    ]
    out.extend(result.lines)
    root = Path(os.environ.get("NANOCLAW_ROOT", str(ROOT)))
    runway = _runway_lines(root, hours=result.hours)
    out.append(
        "runway (last 3 FE STABLE RUNWAY; DERISK [evaluate]=gate probe, [exec-plan]=swap queued):"
    )
    if runway:
        out.extend(f"  {ln}" for ln in runway)
    else:
        out.append("  (none in real_cron.log)")
    out.append("")
    out.append(f"OVERALL: {'PASS' if result.overall_pass else 'FAIL'}")
    if result.trading_allowed() and result.overall_pass:
        out.append("TRADING: allowed (all gates pass)")
    elif result.readiness_pass:
        out.append("TRADING: blocked (PnL/window/pause gate — stay paused or wait)")
    else:
        out.append("TRADING: blocked (hard readiness gate)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Portfolio green gate (configurable window).")
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Lookback window hours from portfolio_history.csv (default: env or 12)",
    )
    parser.add_argument(
        "--session-min-pct",
        type=float,
        default=None,
        help="Min session PnL %% to pass (default: env or -1.0)",
    )
    parser.add_argument(
        "--window-min-pct",
        type=float,
        default=None,
        help="Min window PnL %% over --hours (default: env or -2.0)",
    )
    args = parser.parse_args(argv)

    root = Path(os.environ.get("NANOCLAW_ROOT", str(ROOT)))
    env = _read_env(root)
    hours = float(args.hours if args.hours is not None else _env_float(env.get("EXTERNAL_AUTO_GREEN_HOURS"), 12.0))
    session_min = float(
        args.session_min_pct
        if args.session_min_pct is not None
        else _env_float(env.get("EXTERNAL_AUTO_SESSION_MIN_PCT"), -1.0)
    )
    window_min = float(
        args.window_min_pct
        if args.window_min_pct is not None
        else _env_float(env.get("EXTERNAL_AUTO_WINDOW_MIN_PCT"), -2.0)
    )

    result = evaluate_green_gate(
        root,
        hours=hours,
        session_min_pct=session_min,
        window_min_pct=window_min,
    )
    control = _load_control(root)
    print(
        format_report(
            result,
            paused=bool(control.get("paused")),
            reason=str(control.get("reason") or ""),
        )
    )
    return 0 if result.overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
