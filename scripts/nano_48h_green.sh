#!/usr/bin/env bash
# Back-compat wrapper — same as nanogreen with 48h window label.
exec "$(dirname "${BASH_SOURCE[0]}")/nano_green.sh" --hours 48 "$@"
