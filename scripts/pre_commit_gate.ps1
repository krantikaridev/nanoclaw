Write-Host "=== Nanoclaw pre-commit gate (PowerShell) ==="

Write-Host "[1/5] ruff"
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/5] compileall"
python -m compileall -q .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/5] pytest + coverage"
python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/5] changed files"
git diff --name-only

Write-Host "[5/5] status"
git status --short

Write-Host "✅ Pre-commit gate passed"
