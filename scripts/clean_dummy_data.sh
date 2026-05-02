#!/usr/bin/env bash
# portfolio_history hygiene: retain CSV snapshots whose timestamps belong to cycles
# that ended in a logged on-chain swap ("Swap executed successfully!" in real_cron.log).
# Backs up the CSV first; stamps AI_CONTEXT.md via marker CSV_CLEAN_DUMMY_DATA_TS.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CSV="${ROOT}/portfolio_history.csv"
LOG="${ROOT}/real_cron.log"
CTX="${ROOT}/AI_CONTEXT.md"
MARKER="CSV_CLEAN_DUMMY_DATA_TS"

cd "${ROOT}"

python3 - "${CSV}" "${LOG}" "${CTX}" "${MARKER}" <<'PY'
import csv
import pathlib
import re
import shutil
import sys
from datetime import datetime, timezone

csv_path = pathlib.Path(sys.argv[1])
log_path = pathlib.Path(sys.argv[2])
ctx_path = pathlib.Path(sys.argv[3])
marker = sys.argv[4]

if not csv_path.is_file():
    sys.stderr.write(f"Missing {csv_path}; nothing to clean.\n")
    sys.exit(2)
if not log_path.is_file():
    sys.stderr.write(f"Missing {log_path}; cannot correlate swaps.\n")
    sys.exit(2)
if marker not in ctx_path.read_text(encoding="utf-8"):
    sys.stderr.write(f"Marker {marker!r} not found in AI_CONTEXT.md\n")
    sys.exit(2)

bak = csv_path.with_suffix(csv_path.suffix + f".bak.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
shutil.copy2(csv_path, bak)

raw = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
cycle_re = re.compile(r"=== CYCLE\s+(\d+)\s*\|")

swap_cycle_ts: list[int] = []
last_cycle: int | None = None
for line in raw:
    m = cycle_re.search(line)
    if m:
        try:
            last_cycle = int(m.group(1))
        except ValueError:
            continue
        continue
    if "Swap executed successfully!" in line and last_cycle is not None:
        swap_cycle_ts.append(last_cycle)

if not swap_cycle_ts:
    sys.stderr.write(
        "No swap markers found in real_cron.log — abort without rewriting CSV "
        "(add swaps or investigate log rotation).\n"
    )
    sys.exit(3)

WINDOW = 3600  # seconds: portfolio snapshot logged at cycle start vs swap shortly after


def iso_to_unix(cell: str) -> float | None:
    cell = cell.strip()
    try:
        if cell.endswith("Z"):
            dt = datetime.fromisoformat(cell.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(cell)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def near_swap(ts: float) -> bool:
    return any(abs(ts - float(u)) <= WINDOW for u in swap_cycle_ts)


rows_kept = 0
rows_total = 0
with csv_path.open("r", encoding="utf-8", newline="") as fh_in:
    reader = csv.reader(fh_in)
    rows = list(reader)
if len(rows) < 2:
    sys.stderr.write("CSV has header only or malformed — abort.\n")
    sys.exit(4)
header = rows[0]
exp = ["timestamp", "usdt", "usdc", "wmatic", "pol", "pol_usd_price", "total_value"]
if header[: len(exp)] != exp:
    sys.stderr.write(f"Unexpected header {header}; expected {exp}\n")
    sys.exit(4)

filtered: list[list[str]] = [header]
for row in rows[1:]:
    rows_total += 1
    if not row:
        continue
    ts_unix = iso_to_unix(row[0])
    if ts_unix is not None and near_swap(ts_unix):
        filtered.append(row)
        rows_kept += 1

with csv_path.open("w", encoding="utf-8", newline="") as fh_out:
    csv.writer(fh_out).writerows(filtered)

stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d (UTC)")
text = ctx_path.read_text(encoding="utf-8")
if marker not in text:
    sys.stderr.write(f"Lost marker during run?\n")
    sys.exit(2)
updated = text.replace(marker, stamp, 1)
ctx_path.write_text(updated, encoding="utf-8")

print(f"Backup: {bak}")
print(f"Rows before: {rows_total} → kept near logged swaps (±{WINDOW}s): {rows_kept}")
print(f"AI_CONTEXT.md stamped: {stamp}")
PY
