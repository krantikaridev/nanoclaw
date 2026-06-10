#!/usr/bin/env bash
set -euo pipefail

echo "=== Nanoclaw pre-commit gate ==="
echo "[0/7] secret pattern guard"
python scripts/check_committed_secrets.py --all-tracked

echo "[1/7] ruff"
python -m ruff check .

echo "[2/7] compileall"
python -m compileall -q .

echo "[3/7] pytest + coverage"
python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml

echo "[4/7] env.example sync + key coverage"
if [[ -f ".env" ]]; then
  python scripts/nanoenv_example.py --write
fi
python scripts/verify_env_example_keys.py

echo "[5/7] changed files"
git diff --name-only

echo "[6/7] status"
git status --short

echo "✅ Pre-commit gate passed"
