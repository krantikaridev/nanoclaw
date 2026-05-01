@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0pre_commit_gate.ps1"
exit /b %ERRORLEVEL%
