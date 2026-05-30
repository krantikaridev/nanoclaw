#!/usr/bin/env bash
# 48h-green operator snapshot: session PnL gate, pause discipline, FE share, runway lines.
# Usage: cd nanoclaw && bash scripts/nano_48h_green.sh
# Env: NANOCLAW_ROOT (default: repo root inferred from this script).
set -euo pipefail

ROOT="${NANOCLAW_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "${ROOT}" || {
  echo "nano_48h_green: cannot cd to ${ROOT}" >&2
  exit 1
}

if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

PYTHON="python3"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

exec "${PYTHON}" - <<'PY'
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pnl_report import (  # noqa: E402
    get_current_balance,
    resolve_session_baseline,
)

LOG_FILE = ROOT / "real_cron.log"
CONTROL_FILE = ROOT / "control.json"

PAUSE_LINE_RE = re.compile(r"\[CONTROL\]\s+paused=True", re.IGNORECASE)
EXEC_SUCCESS_RE = re.compile(r"EXEC SUCCESS")
FE_RUNWAY_RE = re.compile(r"FE STABLE RUNWAY")
WALLET_TOTAL_RE = re.compile(
    r"WALLET TOTAL USD\s*\|\s*TOTAL=\$?([\d.]+).*?\|\s*FE_USD=\$?([\d.]+)",
    re.IGNORECASE,
)


def _read_log_lines() -> list[str]:
    if not LOG_FILE.is_file():
        return []
    return LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()


def _load_control() -> dict:
    if not CONTROL_FILE.is_file():
        return {}
    try:
        raw = json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _session_pnl_check() -> tuple[bool, str]:
    bal = get_current_balance()
    if not bal:
        return False, "no balance (pnl_report could not resolve TOTAL)"
    total = float(bal["total"])
    session_total, session_started_at = resolve_session_baseline(total, reset=False)
    session_delta = total - session_total
    session_pct = (session_delta / session_total * 100.0) if session_total else 0.0
    ok = session_delta >= -1e-9
    status = "PASS" if ok else "FAIL"
    detail = (
        f"Session PnL ${session_delta:+.2f} ({session_pct:+.2f}%) "
        f"(seed ${session_total:.2f} @ {session_started_at})"
    )
    return ok, f"{status} | {detail}"


def _pause_exec_check(lines: list[str], paused: bool) -> tuple[bool, str]:
    if not paused:
        return True, "PASS | control.json paused=false (entry exec allowed)"

    last_pause_idx = None
    for idx, line in enumerate(lines):
        if PAUSE_LINE_RE.search(line):
            last_pause_idx = idx

    if last_pause_idx is None:
        return False, "FAIL | paused=true but no [CONTROL] paused=True line in real_cron.log"

    post_pause = lines[last_pause_idx + 1 :]
    violations = [line for line in post_pause if EXEC_SUCCESS_RE.search(line)]
    if violations:
        sample = violations[0].strip()
        if len(sample) > 120:
            sample = sample[:117] + "..."
        return False, f"FAIL | {len(violations)} EXEC SUCCESS after pause | first={sample!r}"

    pause_line = lines[last_pause_idx].strip()
    if len(pause_line) > 120:
        pause_line = pause_line[:117] + "..."
    return True, f"PASS | paused=true, no EXEC SUCCESS after pause | marker={pause_line!r}"


def _fe_share_estimate() -> str:
    fe_usd: float | None = None
    total: float | None = None
    source = "unknown"

    try:
        from modules import runtime

        balances = runtime.get_balances()
        total = float(runtime.compute_authoritative_total_usd(balances))
        fe_usd = float(balances.followed_equity_usd)
        if total > 0 and fe_usd >= 0:
            source = "runtime"
    except Exception:
        pass

    if total is None or fe_usd is None or total <= 0:
        for line in reversed(_read_log_lines()):
            match = WALLET_TOTAL_RE.search(line)
            if match:
                total = float(match.group(1))
                fe_usd = float(match.group(2))
                source = "real_cron.log WALLET TOTAL USD"
                break

    if total is None or fe_usd is None or total <= 0:
        return "n/a (no TOTAL/FE_USD from runtime or log)"

    share = fe_usd / total
    return (
        f"fe_share={share:.1%} (FE_USD=${fe_usd:.2f} / TOTAL=${total:.2f}, source={source})"
    )


def _last_runway_lines(lines: list[str], n: int = 3) -> list[str]:
    hits = [line.strip() for line in lines if FE_RUNWAY_RE.search(line)]
    return hits[-n:]


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== nano_48h_green | {now} UTC ===")
    print()

    control = _load_control()
    paused = bool(control.get("paused"))
    print(f"control: paused={paused} reason={control.get('reason', '')!r}")
    print()

    lines = _read_log_lines()

    session_ok, session_line = _session_pnl_check()
    print(f"session_pnl: {session_line}")

    pause_ok, pause_line = _pause_exec_check(lines, paused)
    print(f"pause_exec:  {pause_line}")

    print(f"fe_share:    {_fe_share_estimate()}")

    runway = _last_runway_lines(lines, 3)
    print("runway (last 3 FE STABLE RUNWAY):")
    if runway:
        for line in runway:
            print(f"  {line}")
    else:
        print("  (none in real_cron.log)")

    overall_ok = session_ok and pause_ok
    print()
    print(f"OVERALL: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
PY
