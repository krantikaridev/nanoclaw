#!/bin/bash
cd ~/.nanobot/workspace/nanoclaw && source .venv/bin/activate
git add nanoclaw.log portfolio_history.csv 2>/dev/null || true
git commit -m "chore: auto-update logs" 2>/dev/null || true
git stash
git pull --rebase origin V2
git stash pop 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
nanoup
nanomon
