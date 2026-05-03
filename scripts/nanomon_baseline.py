#!/usr/bin/env python3
"""Print resolved portfolio baseline (USD) for nanomon.sh; see modules.baseline."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.baseline import resolve_portfolio_baseline_usd  # noqa: E402

if __name__ == "__main__":
    fall = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    print(f"{resolve_portfolio_baseline_usd(fall):.2f}")
