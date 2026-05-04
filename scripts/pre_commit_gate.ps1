Write-Host "=== Nanoclaw pre-commit gate (PowerShell) ==="

Write-Host "[0/7] secret pattern guard"
python scripts/check_committed_secrets.py --all-tracked
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[1/7] ruff"
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/7] compileall"
python -m compileall -q .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/7] pytest + coverage"
python -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered --cov-report=xml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/7] env.example sync + key coverage"
if (Test-Path ".env") {
    python scripts/nanoenv_example.py --write
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
python scripts/verify_env_example_keys.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[5/7] changed files"
git diff --name-only

Write-Host "[6/7] status"
git status --short

Write-Host "✅ Pre-commit gate passed"
