Write-Host "=== Nanoclaw pre-commit gate (PowerShell) ==="

Write-Host "[1/6] ruff"
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/6] compileall"
python -m compileall -q .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/6] pytest + coverage"
python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/6] env.example key coverage"
python scripts/verify_env_example_keys.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[5/6] changed files"
git diff --name-only

Write-Host "[6/6] status"
git status --short

Write-Host "✅ Pre-commit gate passed"
