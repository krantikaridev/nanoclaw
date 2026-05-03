#!/usr/bin/env bash
# Compact status: tail log, LAST TRADE SUMMARY, colors (see scripts/nanomon.py).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/scripts/nanomon.py" "$@"
