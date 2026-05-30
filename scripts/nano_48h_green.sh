#!/usr/bin/env bash
# Back-compat wrapper — same as nanogreen with 48h window label.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/nano_green.sh" --hours 48 "$@"
