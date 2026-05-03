"""Portfolio baseline for PnL labels (nanomon, reports): env → local JSON → CSV first row → live fallback."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Optional operator file (gitignored pattern in .gitignore); wallet must match WALLET for trust.
_BASELINE_JSON = Path("portfolio_baseline.json")
_CSV = Path("portfolio_history.csv")


def resolve_portfolio_baseline_usd(last_total_fallback: float) -> float:
    """
    Precedence:
    1) PORTFOLIO_BASELINE_USD in environment, if set to a **non-zero** number.
       ``0`` (or empty) means "not pinned" — same as unset; continue to 2.
    2) portfolio_baseline.json { \"wallet\", \"baseline_usd\" } if wallet matches env WALLET
    3) First data row of portfolio_history.csv (total_value column)
    4) last_total_fallback (current on-chain total from caller)
    """
    load_dotenv()
    load_dotenv(".env.local", override=True)

    env_wallet = (os.getenv("WALLET") or "").strip().lower()
    env_baseline = (os.getenv("PORTFOLIO_BASELINE_USD") or "").strip()
    if env_baseline:
        v = float(env_baseline)
        if v != 0.0:
            return v

    if _BASELINE_JSON.is_file():
        try:
            data = json.loads(_BASELINE_JSON.read_text(encoding="utf-8"))
            f_wallet = str(data.get("wallet", "")).strip().lower()
            if (not f_wallet) or (f_wallet == env_wallet) or (not env_wallet):
                return float(data["baseline_usd"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            pass

    if _CSV.is_file():
        try:
            with _CSV.open(encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                if not header:
                    pass
                else:
                    first = next(reader, None)
                    if first and len(first) >= 7:
                        return float(first[6].strip())
        except (ValueError, OSError, StopIteration):
            pass

    return float(last_total_fallback)
