#!/usr/bin/env bash
set -euo pipefail

echo "=== Nanoclaw pre-commit gate ==="
echo "[1/4] compileall"
python -m compileall -q .

echo "[2/4] pytest"
python -m pytest -q

echo "[3/4] changed files"
git diff --name-only

echo "[4/4] status"
git status --short

echo "✅ Pre-commit gate passed"
