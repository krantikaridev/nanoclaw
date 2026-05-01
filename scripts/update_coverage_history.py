from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "coverage"
JSON_REPORT = ARTIFACT_DIR / "coverage.json"
HISTORY_FILE = ROOT / "docs" / "COVERAGE_HISTORY.md"

TRACKED_MODULES = [
    "clean_swap.py",
    "swap_executor.py",
    "protection.py",
    "nanoclaw/strategies/signal_equity_trader.py",
    "nanoclaw/utils/gas_protector.py",
]


def _run_coverage() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--cov=.",
        f"--cov-report=json:{JSON_REPORT}",
        "-q",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)


def _pct(value: float | int) -> str:
    return f"{float(value):.1f}%"


def _read_percentages() -> tuple[str, dict[str, str]]:
    payload = json.loads(JSON_REPORT.read_text(encoding="utf-8"))
    total_pct = _pct(payload["totals"]["percent_covered"])
    raw_files = payload.get("files", {})
    file_map = {path.replace("\\", "/"): data for path, data in raw_files.items()}
    module_pcts: dict[str, str] = {}
    for module in TRACKED_MODULES:
        info = file_map.get(module)
        if not info:
            module_pcts[module] = "N/A"
            continue
        module_pcts[module] = _pct(info["summary"]["percent_covered"])
    return total_pct, module_pcts


def _ensure_header() -> None:
    if HISTORY_FILE.exists():
        return
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Coverage History\n\n"
        "Track critical-module coverage over time (ROI-first focus).\n\n"
        "| Timestamp (UTC) | Total | clean_swap | swap_executor | protection | signal_equity_trader | gas_protector |\n"
        "|---|---:|---:|---:|---:|---:|---:|\n"
    )
    HISTORY_FILE.write_text(header, encoding="utf-8")


def _append_row(total_pct: str, module_pcts: dict[str, str]) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    row = (
        f"| {timestamp} | {total_pct} | "
        f"{module_pcts['clean_swap.py']} | "
        f"{module_pcts['swap_executor.py']} | "
        f"{module_pcts['protection.py']} | "
        f"{module_pcts['nanoclaw/strategies/signal_equity_trader.py']} | "
        f"{module_pcts['nanoclaw/utils/gas_protector.py']} |\n"
    )
    with HISTORY_FILE.open("a", encoding="utf-8") as fh:
        fh.write(row)


def main() -> int:
    _run_coverage()
    total_pct, module_pcts = _read_percentages()
    _ensure_header()
    _append_row(total_pct, module_pcts)
    print(f"Updated {HISTORY_FILE.relative_to(ROOT)}")
    print(f"Total coverage: {total_pct}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
