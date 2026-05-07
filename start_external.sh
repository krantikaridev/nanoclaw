#!/bin/bash
set -e
echo "=== Starting External Risk Layer ==="
cd "$(dirname "$0")"
python external_layer/control.py
