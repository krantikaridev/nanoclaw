#!/usr/bin/env bash
set -euo pipefail

# Creates a shareable runtime bundle for analysis (local/drive upload).
# Intentionally excludes .env and any secret-bearing files.

OUT_DIR="artifacts/share"
TS="$(date +%Y%m%d_%H%M%S)"
BUNDLE="${OUT_DIR}/nanoclaw_runtime_${TS}.tar.gz"

mkdir -p "${OUT_DIR}"

FILES=()
for f in portfolio_history.csv trade_exits.json bot_state.json real_cron.log followed_equities.json AI_CONTEXT.md; do
  if [[ -f "$f" ]]; then
    FILES+=("$f")
  fi
done

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No runtime files found to package."
  exit 1
fi

tar -czf "${BUNDLE}" "${FILES[@]}"
echo "Bundle created: ${BUNDLE}"
echo "Included files:"
printf '  - %s\n' "${FILES[@]}"
echo "Upload this bundle to Drive and share link for analysis."
