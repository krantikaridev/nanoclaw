"""Central configuration - Single Source of Truth (SRP)"""

import os
from dataclasses import dataclass


def default_json_rpc_url() -> str:
    """JSON-RPC endpoint for Web3; avoids implicit localhost when ``RPC`` is unset."""
    return (
        os.getenv("RPC")
        or os.getenv("RPC_URL")
        or os.getenv("WEB3_PROVIDER_URI")
        or "https://polygon-rpc.com"
    )


@dataclass
class XSignalConfig:
    TIER_HIGH_MIN: float = float(os.getenv("X_SIGNAL_DYNAMIC_TIER_HIGH_MIN", "0.90"))
    USDC_GTE_TIER_HIGH: float = float(os.getenv("X_SIGNAL_DYNAMIC_USDC_GTE_TIER_HIGH", "20.0"))
    USDC_GTE_FORCE_ELIGIBLE: float = float(
        os.getenv("X_SIGNAL_DYNAMIC_USDC_GTE_FORCE_ELIGIBLE", "15.0")
    )
    USDC_BELOW_FORCE_ELIGIBLE: float = float(
        os.getenv("X_SIGNAL_DYNAMIC_USDC_BELOW_FORCE_ELIGIBLE", "12.0")
    )
    COOLDOWN_SECONDS: int = 1800
    TP_PERCENT: float = 0.12


# Global instance (everyone imports this)
X_SIGNAL = XSignalConfig()

# Other future configs can be added here (e.g. ProtectionConfig, CopyTradeConfig)

# Legacy alias for backward compatibility
X_SIGNAL_FORCE_ELIGIBLE_THRESHOLD = 0.75
