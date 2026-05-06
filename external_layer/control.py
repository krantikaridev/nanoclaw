"""Control command schema and persistence for the external layer."""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# ``python external_layer/control.py`` adds this directory to ``sys.path`` so a plain
# ``risk_checker`` import works; importing via tests/tools does not, so mirror that here.
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# Prefer package-relative import; fall back after direct script execution (no parent package).
try:
    from .risk_checker import evaluate_risk
except ImportError:
    from risk_checker import evaluate_risk

# Resolved project root: parent of ``external_layer/``
CONTROL_JSON_PATH = Path(__file__).resolve().parent.parent / "control.json"


@dataclass(frozen=True)
class CycleControlSnapshot:
    """Per-cycle view of ``control.json`` (missing file → defaults)."""

    paused: bool = False
    # When ``None``, copy paths use ``COPY_TRADE_PCT`` from env / runtime façade.
    max_copy_trade_pct: float | None = None
    # Parsed for future use; not enforced by the trading loop yet.
    force_defensive: bool = False


def _parse_bool(val: object | None, *, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on", "y"}
    return default


def _parse_optional_float(val: object | None) -> float | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        out = float(val)
        return out if out == out else None  # reject NaN
    if isinstance(val, str):
        try:
            out = float(val.strip())
            return out if out == out else None
        except ValueError:
            return None
    return None


def load_cycle_control(path: Path | None = None) -> CycleControlSnapshot:
    """Load operator controls from JSON; on missing/invalid file return defaults."""
    target = path if path is not None else CONTROL_JSON_PATH
    try:
        raw_text = target.read_text(encoding="utf-8").strip()
        if not raw_text:
            return CycleControlSnapshot()
        data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return CycleControlSnapshot()

    if not isinstance(data, dict):
        return CycleControlSnapshot()

    paused = _parse_bool(data.get("paused"), default=False)
    force_defensive = _parse_bool(data.get("force_defensive"), default=False)

    max_pct: float | None = None
    if "max_copy_trade_pct" in data:
        max_pct = _parse_optional_float(data.get("max_copy_trade_pct"))

    return CycleControlSnapshot(
        paused=paused,
        max_copy_trade_pct=max_pct,
        force_defensive=force_defensive,
    )


@dataclass
class ControlCommand:
    """Fields mirrored in ``control.json`` for operator/agent control."""

    paused: bool = False
    max_copy_trade_pct: float = 0.08
    force_defensive: bool = False
    last_updated: str = ""

    def to_dict(self) -> dict[str, bool | float | str]:
        return asdict(self)


def write_control(command: dict) -> None:
    """Serialize ``command`` as JSON to ``control.json`` at the project root."""
    CONTROL_JSON_PATH.write_text(
        json.dumps(command, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# Last successful ``evaluate_risk`` result so we can keep ``control.json`` stable if RPC fails.
_last_successful_risk: dict[str, bool | str | float] | None = None


def _risk_to_control_payload(risk: dict[str, bool | str | float]) -> dict[str, object]:
    """Build the JSON payload for ``control.json`` (balances are not persisted)."""
    payload: dict[str, object] = {
        "paused": bool(risk["paused"]),
        "max_copy_trade_pct": ControlCommand.max_copy_trade_pct,
        "force_defensive": False,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    reason = risk.get("reason")
    if isinstance(reason, str) and reason:
        payload["reason"] = reason
    return payload


def update_control() -> dict[str, bool | str | float]:
    """Refresh ``control.json`` from live risk evaluation.

    Calls ``evaluate_risk()`` then overwrites the repo-root JSON file so
    nanoclaw's trading loop (via ``load_cycle_control``) picks up ``paused``
    and optional ``reason`` on the next cycle. Keeps other knobs at defaults so
    the file stays valid for existing parsers.

    If balance reads fail, logs a warning and keeps the previous paused/reason
    (and rewrites ``control.json`` from the last good evaluation when available).
    """
    global _last_successful_risk

    try:
        risk = evaluate_risk()
        _last_successful_risk = dict(risk)
        write_control(_risk_to_control_payload(risk))
        return risk

    except Exception as exc:  # noqa: BLE001 — RPC / contract errors should not kill the loop
        print(
            f"[EXTERNAL] WARNING: Balance check failed ({exc!s}). "
            "Keeping previous trading pause state.",
            flush=True,
        )
        if _last_successful_risk is not None:
            risk = dict(_last_successful_risk)
            write_control(_risk_to_control_payload(risk))
            return risk

        snap = load_cycle_control()
        # Omit balances — operator line prints "(unknown)" until the next good RPC read.
        out: dict[str, bool | str | float] = {"paused": snap.paused}
        return out


def _format_balance_line(risk: dict[str, bool | str | float]) -> str:
    usdt = risk.get("usdt_balance")
    wmatic = risk.get("wmatic_balance")
    if (
        isinstance(usdt, (int, float))
        and isinstance(wmatic, (int, float))
        and not math.isnan(float(usdt))
        and not math.isnan(float(wmatic))
    ):
        return f"USDT: {float(usdt):.2f} | WMATIC: {float(wmatic):.4f}"
    return "USDT: (unknown) | WMATIC: (unknown)"


def _run_control_loop(interval_seconds: float = 25.0) -> None:
    """Poll ``update_control()`` forever for standalone operator processes.

    Default interval is 25 seconds (within the 20–30s operator window).
    """
    while True:
        risk = update_control()
        paused = bool(risk.get("paused"))
        bal = _format_balance_line(risk)
        trading = "PAUSED" if paused else "ACTIVE"
        reason = risk.get("reason")
        reason_txt = (
            f" | Reason: {reason}"
            if paused and isinstance(reason, str) and reason
            else ""
        )
        print(
            f"[EXTERNAL] {bal} | Trading: {trading}{reason_txt}",
            flush=True,
        )
        time.sleep(interval_seconds)


if __name__ == "__main__":
    # Runnable as: ``python external_layer/control.py`` — writes ``control.json`` periodically.
    _run_control_loop()
