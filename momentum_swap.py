import asyncio
from clean_swap import *  # reuse all guardrails, approve_and_swap, state, etc.

async def main():
    print("🚀 Momentum Strategy Starting")
    # Simple momentum bias (expand later)
    # Example: run the same guarded logic for now
    # Future: check recent WETH price change and bias larger buy or stronger rebalance
    await main()  # reuse existing main with guardrails for safety

if __name__ == "__main__":
    asyncio.run(main())
