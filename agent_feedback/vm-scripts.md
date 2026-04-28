# Task Log: VM Recovery + Health Scripts

## Outcome

- Added `scripts/fix_vm.sh` (executable) to recover from common VM stuck states:
  - kills stray `node` processes
  - detects zombie processes and terminates their parent PIDs (SIGTERM, then SIGKILL best-effort)
  - drops Linux page cache (best-effort, requires sudo)
  - stops `clean_swap.py` so cron can restart cleanly
- Added `scripts/vm_health.sh` (executable) for a fast “one shot” diagnostic snapshot:
  - CPU/load, memory, storage, disk I/O (if `iostat` exists), bot processes, cron presence, recent logs
  - RPC probe with timeout and explicit OK/FAILED/INCONCLUSIVE status

## Why it matters

- Reduces mean-time-to-recovery when the VM is sluggish or the bot gets wedged.
- Makes health checks actionable by surfacing clear failure modes instead of silent/partial output.

## Follow-ups

- Optionally read `RPC` from `.env.local` (when present) so the default endpoint isn’t duplicated in multiple places.
- Consider logging health check output to a timestamped file in an artifacts directory for later post-mortems.

