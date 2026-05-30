"""Static audit helpers for ``followed_wallets.json`` (copy-trade targets).

Copy trading follows **EOA trader wallets**, not Polygon token/router contracts.
See ``docs/COPY_TRADING_AUDIT.md`` and ``scripts/copy_trading_audit.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

WalletCategory = Literal["tradeable", "token_contract", "invalid"]

# Polygon mainnet token / system contracts mistakenly listed in followed_wallets.json (May 2026).
# Keys are lowercase checksummed-agnostic hex.
KNOWN_POLYGON_TOKEN_CONTRACTS: dict[str, str] = {
    "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": "DAI",
    "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC",
    "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270": "WMATIC",
    "0x7a8ed27f4c30512326878652d20fc85727401854": "MAI",
    "0x4c569c1e541a19132ac893748e0ad54c7c989ff4": "jarvis_SyntheticEuro",
    "0xd7f199c16dd0dfb5bd66606390332b8ae3403ec4": "SushiSwap_LP",
    "0x2301dc6a50dff4e419983c2d76ec4964f56561b8": "unknown_token_contract",
}


def normalize_address(addr: str) -> str:
    raw = str(addr or "").strip()
    if not raw:
        return ""
    if not raw.startswith("0x"):
        raw = "0x" + raw
    if len(raw) != 42:
        return raw.lower()
    return "0x" + raw[2:].lower()


def classify_wallet(addr: str) -> tuple[WalletCategory, str | None]:
    """Return (category, label). Label set for token contracts."""
    norm = normalize_address(addr)
    if len(norm) != 42 or not norm.startswith("0x"):
        return "invalid", None
    try:
        int(norm[2:], 16)
    except ValueError:
        return "invalid", None
    label = KNOWN_POLYGON_TOKEN_CONTRACTS.get(norm)
    if label:
        return "token_contract", label
    return "tradeable", None


@dataclass
class WalletAuditRow:
    address: str
    category: WalletCategory
    label: str | None = None


@dataclass
class CopyTradingAuditReport:
    wallets: list[WalletAuditRow] = field(default_factory=list)
    copy_trading_enabled: bool = True
    reject_token_contracts: bool = True

    @property
    def tradeable(self) -> list[str]:
        return [r.address for r in self.wallets if r.category == "tradeable"]

    @property
    def token_contracts(self) -> list[WalletAuditRow]:
        return [r for r in self.wallets if r.category == "token_contract"]

    @property
    def invalid(self) -> list[WalletAuditRow]:
        return [r for r in self.wallets if r.category == "invalid"]

    @property
    def ok_for_copy_trading(self) -> bool:
        if not self.copy_trading_enabled:
            return True
        return len(self.tradeable) > 0

    @property
    def exit_code(self) -> int:
        """0=ok, 1=enabled but no tradeable wallets, 2=all listed entries are token contracts."""
        if not self.copy_trading_enabled:
            return 0
        if not self.wallets:
            return 1
        if self.tradeable:
            return 0
        if self.token_contracts and not self.invalid:
            return 2
        return 1

    def lines(self) -> list[str]:
        out: list[str] = []
        out.append(
            f"COPY_TRADING_ENABLED={self.copy_trading_enabled} "
            f"reject_token_contracts={self.reject_token_contracts}"
        )
        out.append(f"wallets_total={len(self.wallets)} tradeable={len(self.tradeable)}")
        for row in self.wallets:
            if row.category == "token_contract":
                out.append(
                    f"  REJECT token_contract | {row.address} | {row.label or 'known_token'}"
                )
            elif row.category == "invalid":
                out.append(f"  REJECT invalid | {row.address}")
            else:
                out.append(f"  OK tradeable | {row.address}")
        if self.copy_trading_enabled and not self.tradeable:
            out.append(
                "ACTION: Replace followed_wallets.json with 1-2 verified trader EOAs "
                "or set COPY_TRADING_ENABLED=false. See docs/COPY_TRADING_AUDIT.md"
            )
        elif self.copy_trading_enabled and self.token_contracts:
            out.append(
                "NOTE: Known token contracts are stripped at runtime when "
                "COPY_TRADING_REJECT_TOKEN_CONTRACTS=true (default)."
            )
        return out


def audit_followed_wallets(
    wallets: list[str],
    *,
    copy_trading_enabled: bool = True,
    reject_token_contracts: bool = True,
) -> CopyTradingAuditReport:
    rows: list[WalletAuditRow] = []
    for raw in wallets:
        norm = normalize_address(raw)
        category, label = classify_wallet(norm)
        if category == "tradeable" and reject_token_contracts:
            rows.append(WalletAuditRow(address=norm, category=category, label=label))
        elif category == "token_contract":
            rows.append(
                WalletAuditRow(
                    address=norm or str(raw),
                    category=category,
                    label=label,
                )
            )
        else:
            rows.append(
                WalletAuditRow(
                    address=norm or str(raw),
                    category=category,
                    label=label,
                )
            )
    return CopyTradingAuditReport(
        wallets=rows,
        copy_trading_enabled=copy_trading_enabled,
        reject_token_contracts=reject_token_contracts,
    )


def filter_tradeable_wallets(
    wallets: list[str],
    *,
    reject_token_contracts: bool = True,
) -> list[str]:
    """Return addresses safe to pass to polycopy / USDC copy (EOAs only by static list)."""
    if not reject_token_contracts:
        return [normalize_address(w) for w in wallets if normalize_address(w)]
    report = audit_followed_wallets(wallets, reject_token_contracts=True)
    return report.tradeable


# Legacy misconfiguration shipped in repo until May 2026 audit.
LEGACY_MISCONFIGURED_WALLETS: tuple[str, ...] = tuple(KNOWN_POLYGON_TOKEN_CONTRACTS.keys())
