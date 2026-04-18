# NanoClaw Grok Context Update (19 Apr 2026)
## Guardrails Added (V2 clean_swap.py)
- Min trade: $2 USD
- Max gas: 90 Gwei
- Cooldown: 30 min (cron every 6h for 10-12hr feedback)
- Auto-rebalance: WETH→USDT when USDT <10 (single ~$9-10 swap)
- POL critical: skip if <2.0 + warning
- Logging: timestamped balances, direction, tx links
Builds on old USDC seed rules, daily loss cap, tax logs.

=== UPDATE 19 Apr 2026 ~02:00 IST ===
Guardrails verified working:
- POL critical check active (skipped at 0.78 POL)
- Min $2 trade enforced
- No micro-swaps possible
- Auto WETH→USDT rebalance ready
Next: Top up 3–5 POL manually, re-test, then set 6h cron for 4 larger cycles/day.
POL price ~$0.0895, WETH ~$2,360–$2,410, gas ~126–130 Gwei.
=== 19 Apr 2026 POL Withdrawal ===
4.51 POL incoming from Binance (Tx 0xc9b9...6c5). Guardrails blocking until POL ≥3.0. Auto WETH→POL option available.
=== 19 Apr 2026 Evening Update ===
- POL topped up to 5.29
- Telegram working
- Cron set every 6 hours
- clean_swap.py running with full guardrails + dynamic gas
- Rebalance (WETH→USDT) attempted multiple times (pending confirmation)
- Plan: Monitor morning, then add 1-2 more strategies (momentum/polymarket) if stable
