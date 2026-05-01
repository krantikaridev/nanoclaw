# Nanoclaw Clean-State Checklist

Use this checklist before every commit/push and every VM deploy.

## 1) Scope and cleanliness

- `git diff --name-only` shows only intended files.
- No accidental edits in unrelated modules.
- No secrets in tracked files (`.env`, private keys, wallet secrets).

## 2) Config consistency (single source of truth)

- Code fallback defaults match `.env.example`.
- Guard threshold names and semantics are aligned (`MIN_POL_FOR_GAS`, cooldown vars, TP vars).
- Docs (`AI_CONTEXT.md`) reflect any behavior/default changes.

## 3) Decision matrix sanity

Verify these branches after guard/log changes:

- gas high / gas ok
- POL low / POL recovered / POL topup fail / topup "success but still low"
- USDC below min / USDC above min
- cooldown active / cooldown expired
- TP base / TP strong / trailing stop

Each branch must have:

- correct control flow (skip/continue/return/execute)
- correct reason string in logs

## 4) Test gate (mandatory)

Run from repo root:

```bash
python -m compileall -q .
python -m pytest -q
```

If either fails, do not commit.

## 5) Pre-deploy gate (VM)

- VM working tree is clean before pull.
- Deploy exact branch/commit intended for release.
- Confirm bot restart and live logs after deploy.

## 6) Post-deploy smoke check

- Env loaded (expected TP/cooldown/POL values).
- Bot starts without tracebacks.
- Decision-path logs show expected guard messages.
