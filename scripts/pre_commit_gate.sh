#!/usr/bin/env bash
set -euo pipefail

echo "=== Nanoclaw pre-commit gate ==="
echo "[1/5] ruff"
python -m ruff check .

echo "[2/5] compileall"
python -m compileall -q .

echo "[3/5] pytest + coverage"
python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml

echo "[4/5] changed files"
git diff --name-only

echo "[5/5] status"
git status --short

echo "✅ Pre-commit gate passed"
