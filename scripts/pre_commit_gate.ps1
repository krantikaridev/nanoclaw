Write-Host "=== Nanoclaw pre-commit gate (PowerShell) ==="

Write-Host "[1/4] compileall"
python -m compileall -q .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/4] pytest"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/4] changed files"
git diff --name-only

Write-Host "[4/4] status"
git status --short

Write-Host "✅ Pre-commit gate passed"
