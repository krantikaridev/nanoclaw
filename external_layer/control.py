"""Control command schema and persistence for the external layer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

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
