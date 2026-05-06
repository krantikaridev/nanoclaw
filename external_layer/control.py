"""Control command schema and persistence for the external layer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# Resolved project root: parent of ``external_layer/``
CONTROL_JSON_PATH = Path(__file__).resolve().parent.parent / "control.json"


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
