# NanoClaw Grok Context Update (19 Apr 2026)
## Guardrails Added (V2 clean_swap.py)
- Min trade: $2 USD
- Max gas: 90 Gwei
- Cooldown: 30 min (cron every 6h for 10-12hr feedback)
- Auto-rebalance: WETH→USDT when USDT <10 (single ~$9-10 swap)
- POL critical: skip if <2.0 + warning
- Logging: timestamped balances, direction, tx links
Builds on old USDC seed rules, daily loss cap, tax logs.
