#!/usr/bin/env bash
set -euo pipefail

echo "=== Nanoclaw pre-commit gate ==="
echo "[1/6] ruff"
python -m ruff check .

echo "[2/6] compileall"
python -m compileall -q .

echo "[3/6] pytest + coverage"
python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml

echo "[4/6] env.example sync + key coverage"
if [[ -f ".env" ]]; then
  python scripts/nanoenv_example.py --write
fi
python scripts/verify_env_example_keys.py

echo "[5/6] changed files"
git diff --name-only

echo "[6/6] status"
git status --short

echo "✅ Pre-commit gate passed"
