# External layer

<!-- This folder contains the new External Risk + Agent Layer: JSON control surface (`control.json`), helpers in `control.py`, and risk hooks in `risk_checker.py`. -->

## Operator loop

Run `python external_layer/control.py` from the repo root to overwrite **`control.json` every 30 seconds** with the latest risk evaluation (`paused`, optional `reason`, plus defaults nanoclaw already reads). Stop with Ctrl+C.
