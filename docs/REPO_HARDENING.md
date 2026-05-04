# Repository Hardening Checklist

Purpose: make secret leakage and accidental `.env` pushes hard to bypass, even under operator error.

## Priority TODO (platform-side)

- [ ] Enable branch protection for `main`/`master`/`dev`/`V2`.
- [ ] Require pull requests before merge.
- [ ] Require status checks to pass before merge.
  - Required check: CI job that runs `scripts/check_committed_secrets.py --all-tracked`.
- [ ] Restrict who can push directly to protected branches.
- [ ] Enable GitHub secret scanning and push protection at repo/org level.
- [ ] Enable "Do not allow bypassing the above settings" for admins where policy allows.

## Repo-side guards already present

- Local/VM git hooks:
  - `.githooks/pre-commit` -> staged secret scan.
  - `.githooks/pre-push` -> tracked-files secret scan.
- CI guard:
  - `.github/workflows/ci.yml` runs `python3 scripts/check_committed_secrets.py --all-tracked`.
- Operator workflow hardening:
  - `scripts/nanoup.sh` sets `core.hooksPath=.githooks`.
  - `scripts/nanobot_aliases.sh` includes guarded `nanocommit` and `nanopush`.

## Verification command (manual)

Run from repo root:

`python scripts/check_committed_secrets.py --all-tracked`
