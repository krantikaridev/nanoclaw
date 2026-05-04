#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

LOG_FILE = "real_cron.log"
MANUAL_PATTERN = re.compile(
    r"MANUAL CORRECT BALANCE.*USDC=\$?([\d.]+).*WMATIC=\$?([\d.]+).*USDT=\$?([\d.]+).*Source=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
WALLET_PATTERN = re.compile(r"WALLET BALANCE.*USDC=\$?([\d.]+)")
REAL_PATTERN = re.compile(
    r"Real USDT:\s*\$?([\d.]+)\s*\|\s*USDC:\s*\$?([\d.]+)\s*\|\s*WMATIC:\s*\$?([\d.]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BalanceSnapshot:
    usdt: float
    usdc: float
    wmatic: float
    total: float
    source: str
    logger_source: str | None = None


def extract_snapshots(log_file: Path) -> list[BalanceSnapshot]:
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    snapshots: list[BalanceSnapshot] = []
    pending_wallet: tuple[int, float] | None = None

    for idx, line in enumerate(lines):
        manual_match = MANUAL_PATTERN.search(line)
        if manual_match:
            usdc = float(manual_match.group(1))
            wmatic = float(manual_match.group(2))
            usdt = float(manual_match.group(3))
            logger_source = manual_match.group(4)
            snapshots.append(
                BalanceSnapshot(
                    usdt=usdt,
                    usdc=usdc,
                    wmatic=wmatic,
                    total=usdc + usdt + wmatic,
                    source="manual",
                    logger_source=logger_source,
                )
            )
            continue

        wallet_match = WALLET_PATTERN.search(line)
        if wallet_match:
            pending_wallet = (idx, float(wallet_match.group(1)))
            continue

        real_match = REAL_PATTERN.search(line)
        if not real_match:
            continue

        usdt = float(real_match.group(1))
        usdc = float(real_match.group(2))
        wmatic = float(real_match.group(3))
        source = "real"

        if pending_wallet and (idx - pending_wallet[0]) <= 5:
            usdc = pending_wallet[1]
            source = "paired"
        pending_wallet = None

        snapshots.append(
            BalanceSnapshot(
                usdt=usdt,
                usdc=usdc,
                wmatic=wmatic,
                total=usdc + usdt + wmatic,
                source=source,
            )
        )

    return snapshots


def _source_rank(snapshot: BalanceSnapshot) -> int:
    if snapshot.source == "manual" and snapshot.logger_source in {"BotLogger", "AutoLogger"}:
        return 0
    if snapshot.source == "manual":
        return 1
    if snapshot.source == "paired":
        return 2
    return 3


def _source_label(snapshot: BalanceSnapshot) -> str:
    if snapshot.source == "manual" and snapshot.logger_source:
        return f"MANUAL ({snapshot.logger_source})"
    if snapshot.source == "paired":
        return "WALLET+REAL (paired)"
    if snapshot.source == "real":
        return "Real USDT line"
    return "MANUAL"


def get_current_balance():
    snapshots = extract_snapshots(Path(LOG_FILE))
    if not snapshots:
        return None

    for rank in (0, 1, 2, 3):
        for snapshot in reversed(snapshots):
            if _source_rank(snapshot) != rank:
                continue
            if snapshot.total <= 5:
                continue
            if snapshot.source in {"paired", "real"} and snapshot.wmatic >= 15:
                continue
            return {
                "usdt": snapshot.usdt,
                "usdc": snapshot.usdc,
                "wmatic": snapshot.wmatic,
                "total": snapshot.total,
                "source": _source_label(snapshot),
            }

    return None

def get_recent_trades(n=8):
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    trades = []
    for line in reversed(lines):
        if any(kw in line for kw in ["REAL TX HASH", "Swap executed", "PROTECTION TRIGGERED", "Swap confirmed"]):
            trades.append(line.strip()[:130])
            if len(trades) >= n:
                break
    return list(reversed(trades))

# === REPORT ===
bal = get_current_balance()

print("═══════════════════════════════════════════════")
print("           NANOC LAW PnL REPORT (FIXED v3)")
print("═══════════════════════════════════════════════")

if bal:
    print(f"💰 CURRENT BALANCE  (source: {bal['source']})")
    print(f"   USDC:   ${bal['usdc']:.2f}")
    print(f"   WMATIC: ${bal['wmatic']:.2f}")
    print(f"   USDT:   ${bal['usdt']:.2f}")
    print(f"   TOTAL:  ${bal['total']:.2f}")
    print()
else:
    print("No valid balance found.")

print("📈 RECENT TRADES (last 8)")
print("═══════════════════════════════════════════════")
for t in get_recent_trades():
    print(t)
print("═══════════════════════════════════════════════")
