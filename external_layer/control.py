"""Control command schema and persistence for the external layer."""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# ``python external_layer/control.py`` must resolve repo-root modules (``config``,
# ``nanoclaw``) and this folder (plain ``risk_checker`` import when ``__package__`` is unset).
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
_THIS_DIR = str(Path(__file__).resolve().parent)
for _p in (_REPO_ROOT, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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
    # Optional operator message from the external layer (logging only in nanoclaw).
    reason: str | None = None


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

    reason_raw = data.get("reason")
    reason: str | None = None
    if isinstance(reason_raw, str) and reason_raw.strip():
        reason = reason_raw.strip()

    return CycleControlSnapshot(
        paused=paused,
        max_copy_trade_pct=max_pct,
        force_defensive=force_defensive,
        reason=reason,
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


def _optional_json_balance(val: object) -> float | None:
    """Finite float suitable for JSON ``usdt_balance`` / ``wmatic_balance`` fields."""
    if isinstance(val, (int, float)):
        f = float(val)
        if f == f and not math.isnan(f):
            return f
    return None


def _risk_to_control_payload(risk: dict[str, bool | str | float]) -> dict[str, object]:
    """Build the JSON payload for ``control.json`` (includes live balances when known)."""
    raw_pct = risk.get("max_copy_trade_pct")
    if isinstance(raw_pct, (int, float)) and raw_pct == raw_pct:
        max_pct = float(raw_pct)
    else:
        max_pct = float(ControlCommand.max_copy_trade_pct)

    payload: dict[str, object] = {
        "paused": bool(risk["paused"]),
        "max_copy_trade_pct": max_pct,
        "force_defensive": False,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    reason = risk.get("reason")
    if isinstance(reason, str) and reason.strip():
        payload["reason"] = reason.strip()
    u = _optional_json_balance(risk.get("usdt_balance"))
    uc = _optional_json_balance(risk.get("usdc_balance"))
    s = _optional_json_balance(risk.get("stable_usd"))
    w = _optional_json_balance(risk.get("wmatic_balance"))
    if u is not None:
        payload["usdt_balance"] = u
    if uc is not None:
        payload["usdc_balance"] = uc
    if s is not None:
        payload["stable_usd"] = s
    if w is not None:
        payload["wmatic_balance"] = w
    return payload


def _load_full_control_dict() -> dict[str, object]:
    """Raw ``control.json`` object for merge paths (heartbeat on RPC failure)."""
    try:
        raw = CONTROL_JSON_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return dict(data) if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _heartbeat_payload_after_failure(*, snap: CycleControlSnapshot) -> dict[str, object]:
    """Preserve on-disk ``paused`` / ``reason`` / knobs; always refresh ``last_updated``."""
    existing = _load_full_control_dict()
    paused = _parse_bool(existing.get("paused"), default=snap.paused)
    max_pct = _parse_optional_float(existing.get("max_copy_trade_pct"))
    if max_pct is None:
        max_pct = ControlCommand.max_copy_trade_pct
    force_defensive = _parse_bool(existing.get("force_defensive"), default=False)
    payload: dict[str, object] = {
        "paused": paused,
        "max_copy_trade_pct": max_pct,
        "force_defensive": force_defensive,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    reason = existing.get("reason")
    if isinstance(reason, str) and reason:
        payload["reason"] = reason
    # Keep last known on-chain balances visible while RPC is down.
    u = _optional_json_balance(existing.get("usdt_balance"))
    uc = _optional_json_balance(existing.get("usdc_balance"))
    s = _optional_json_balance(existing.get("stable_usd"))
    w = _optional_json_balance(existing.get("wmatic_balance"))
    if u is not None:
        payload["usdt_balance"] = u
    if uc is not None:
        payload["usdc_balance"] = uc
    if s is not None:
        payload["stable_usd"] = s
    if w is not None:
        payload["wmatic_balance"] = w
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
        _log_external_risk_line(risk, tag="control.json")
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
            _log_external_risk_line(risk, tag="stale_cache")
            return risk

        # No successful RPC yet this process: still rewrite JSON so ``last_updated``
        # moves and operators can see the loop is alive (preserves file contents).
        snap = load_cycle_control()
        payload = _heartbeat_payload_after_failure(snap=snap)
        write_control(payload)
        print(
            "[EXTERNAL] heartbeat | refreshed last_updated only (no fresh balances) | "
            f"paused={payload['paused']} max_copy_trade_pct={payload['max_copy_trade_pct']}",
            flush=True,
        )
        out: dict[str, bool | str | float] = {
            "paused": bool(payload["paused"]),
            "max_copy_trade_pct": float(payload["max_copy_trade_pct"]),
        }
        r = payload.get("reason")
        if isinstance(r, str) and r:
            out["reason"] = r
        u = _optional_json_balance(payload.get("usdt_balance"))
        uc = _optional_json_balance(payload.get("usdc_balance"))
        s = _optional_json_balance(payload.get("stable_usd"))
        w = _optional_json_balance(payload.get("wmatic_balance"))
        if u is not None:
            out["usdt_balance"] = u
        if uc is not None:
            out["usdc_balance"] = uc
        if s is not None:
            out["stable_usd"] = s
        if w is not None:
            out["wmatic_balance"] = w
        return out


def _log_external_risk_line(risk: dict[str, bool | str | float], *, tag: str = "decision") -> None:
    """Stdout trace for operators: what the external layer wrote to ``control.json``."""
    paused = bool(risk.get("paused"))
    mcp = risk.get("max_copy_trade_pct", "?")
    reason = risk.get("reason")
    reason_txt = f" | reason={reason}" if isinstance(reason, str) and reason else ""
    bal = _format_balance_line(risk)
    trading = "PAUSED" if paused else "ACTIVE"
    print(
        f"[EXTERNAL] {tag} | trading={trading} | max_copy_trade_pct={mcp}{reason_txt} | {bal}",
        flush=True,
    )


def _format_balance_line(risk: dict[str, bool | str | float]) -> str:
    """One-line balances for `[EXTERNAL]` logs (matches risk tier inputs)."""

    def _nf(x: object) -> bool:
        return isinstance(x, (int, float)) and not math.isnan(float(x))

    usdt = risk.get("usdt_balance")
    stable = risk.get("stable_usd")
    wmatic = risk.get("wmatic_balance")
    usdc = risk.get("usdc_balance")
    bits: list[str] = [
        f"USDT: {float(usdt):.2f}" if _nf(usdt) else "USDT: ?",
    ]
    if _nf(usdc):
        bits.append(f"USDCΣ: {float(usdc):.2f}")
    if _nf(stable):
        bits.append(f"stables: {float(stable):.2f}")
    bits.append(f"WMATIC: {float(wmatic):.4f}" if _nf(wmatic) else "WMATIC: ?")
    return " | ".join(bits)


def _run_control_loop(interval_seconds: float = 30.0) -> None:
    """Poll ``update_control()`` forever for standalone operator processes.

    Default interval is 30 seconds (operator-visible cadence for ``control.json`` updates).
    """
    while True:
        update_control()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    # Runnable as: ``python external_layer/control.py`` — writes ``control.json`` periodically.
    print(
        "External Risk Layer started. Updating control.json every 30s...",
        flush=True,
    )
    try:
        _run_control_loop()
    except KeyboardInterrupt:
        print(
            "\nExternal Risk Layer stopped (keyboard interrupt). Exiting.",
            flush=True,
        )
