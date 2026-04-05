#!/bin/bash
cd ~/.nanobot/workspace/nanoclaw

echo "=== Real Trade Cron Started at $(date) ===" >> real_cron.log 2>&1

# Force activate venv
source .venv/bin/activate

# Run the script (it will load .env automatically)
python3 real_parallel_runner.py >> real_cron.log 2>&1

echo "=== Real Trade Cron Finished at $(date) ===" >> real_cron.log 2>&1
