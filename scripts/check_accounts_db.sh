#!/usr/bin/env bash
set -euo pipefail

# Stage safety check before removing accounts.db from repo/worktree.
# Rule:
# - 0 rows => safe to remove (prints exact commands)
# - >0 rows => investigate first (do NOT remove yet)

python - <<'PY'
import os
import sqlite3
import sys

db_path = "accounts.db"
has_accounts_table = False
row_count = 0
con = None

if not os.path.exists(db_path):
    print("accounts.db not found -> already safe (nothing to remove).")
    sys.exit(0)

try:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
    has_accounts_table = cur.fetchone() is not None
    if has_accounts_table:
        cur.execute("SELECT COUNT(*) FROM accounts")
        row_count = int(cur.fetchone()[0])
except Exception as exc:
    print(f"BLOCKER: unable to inspect accounts.db safely: {exc}")
    print("Investigate DB corruption/permissions before deletion.")
    sys.exit(2)
finally:
    if con is not None:
        try:
            con.close()
        except Exception:
            pass

print(f"accounts.db present: {db_path}")
print(f"accounts table present: {has_accounts_table}")
print(f"accounts row count: {row_count}")

if has_accounts_table and row_count > 0:
    print("BLOCKER: accounts.db has non-zero rows. Investigate/backup/rotate before deletion.")
    print("Suggested next step: export rows securely, then purge credentials, then rerun this check.")
    sys.exit(2)

print("SAFE_TO_DELETE: zero-row (or no accounts table) state confirmed.")
print("Run:")
print("  git rm --cached accounts.db")
print("  rm -f accounts.db")
print("  echo accounts.db >> .gitignore   # optional if you still generate it locally")
PY
