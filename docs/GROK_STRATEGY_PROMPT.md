# Grok strategy prompt — copy entire block below

Paste into Grok (subscription). Return the full output in a **new Cursor thread** for review against this repo.

---

```
You are advising on nanoclaw — a Polygon spot-swap trading bot (Python, cron every 2 min, ~$130 stage wallet).

## Current state (2026-06-05)

**Stage wallet 0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6:**
- Branch V2 @ tag v2-stage-2026-06-05 (738222ed)
- TOTAL ~$135, ~64% FE (mostly WETH), ~$40 USDC, paused
- auto_pause: session below -1% floor AND 12h window ~-6%
- 0 on-chain fills today; pause_exec PASS (no churn)
- Bleed is mark-to-market (WETH -5%, WMATIC -11%), not ping-pong
- Jun 3 incident: auto_unpause on thin 12h window → 4× X-Signal WMATIC $10-16 buys → discipline breach

**Shipped fixes:**
- V2: window-stress derisk, tiered cooldown 4h, unpause hysteresis, pause_exec discipline (738222ed)
- V4-play branch: dual-window unpause (8h AND 12h), play budget 2 fills/day on books < $200, X-Signal cap $10 when window < 0%

**Constraints:**
- Operator has ~$130 on stage only; dev env must be SMALL separate wallet (~$50 experimental), ephemeral VM (not 24/7), same rotation logic scaled by STAGE_SEED_USD
- 2 free Oracle VMs; wants cloud-agnostic one-command bootstrap/teardown
- Operator returns Monday; wants PnL>0 path, not "sit paused forever"
- Code quality: swap_executor.py monolithic, ~79% test coverage, ruff in CI

## Questions (answer each with tradeoffs)

1. **Immediate PnL path:** Given paused stage with -6% window, is manual WETH→USDC trim ($12-20) net positive vs wait? What FE% target for a $135 book in a choppy ETH tape?

2. **Dev env sizing:** Is ~$50 USDC + ~$1 POL enough to validate V4-play rotation paths (high-stable $10, tiered $8, play budget 2/day)? Challenge our minimums.

3. **Merge priority:** Rank: (a) merge V4-play gates to stage, (b) refactor swap_executor, (c) more assets/copy trading, (d) infra automation, (e) manual trading. What ships before Monday for highest ROI?

4. **48h lab gate:** Is 48h soak with ≤4 fills/day the right merge gate? What simpler gate would you use?

5. **Secrets & ops:** GitHub Secrets vs local ~/.nanoclaw/secrets.dev.env for ephemeral VMs; design a single `nanoremote` command replacing ssh+cd+activate for logs/nano12h.

6. **One-command deploy:** Minimal MVP for dev_bootstrap.sh (SSH-only, destroy and respin) — list exact steps and failure modes.

7. **Code quality:** What metrics beyond 79% coverage matter most before increasing capital? Suggest a 1-week refactor scope that does NOT block PnL fixes.

8. **Honest expectation:** Can a $50 dev book with same logic produce statistically meaningful rotation alpha in 48h? If not, what experiment design do you recommend?

Be direct. Disagree where our plan is wrong. No generic crypto advice — ground answers in this bot architecture.
```

---

After Grok responds, open Cursor with: "Review Grok output against docs/DEV_ENV.md and V4-play; recommend single next commit."
