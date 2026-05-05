"""Lightweight per-wallet copy-trade performance tracking."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import config as cfg


def _store_path() -> Path:
    return Path(str(cfg.COPY_WALLET_PERFORMANCE_FILE)).resolve()


def _default_store() -> dict[str, Any]:
    return {"wallets": {}, "open_positions": []}


def _load_store() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return _default_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            wallets = raw.get("wallets", {})
            opens = raw.get("open_positions", [])
            return {
                "wallets": wallets if isinstance(wallets, dict) else {},
                "open_positions": opens if isinstance(opens, list) else [],
            }
    except Exception:
        pass
    return _default_store()


def _save_store(store: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _wallet_metrics(store: dict[str, Any], wallet: str) -> dict[str, Any]:
    wallets = store.setdefault("wallets", {})
    metrics = wallets.get(wallet)
    if not isinstance(metrics, dict):
        metrics = {"trades": 0, "wins": 0, "total_pnl_usd": 0.0, "recent_pnl_usd": []}
        wallets[wallet] = metrics
    metrics.setdefault("trades", 0)
    metrics.setdefault("wins", 0)
    metrics.setdefault("total_pnl_usd", 0.0)
    metrics.setdefault("recent_pnl_usd", [])
    return metrics


def record_copy_entry(wallet: str, *, entry_price_usd: float, notional_usd: float) -> None:
    if not wallet or float(notional_usd) <= 0.0:
        return
    store = _load_store()
    opens = store.setdefault("open_positions", [])
    opens.append(
        {
            "wallet": str(wallet).strip(),
            "entry_price_usd": float(entry_price_usd),
            "notional_usd": float(notional_usd),
            "opened_at": time.time(),
        }
    )
    _save_store(store)


def _apply_wallet_pnl(metrics: dict[str, Any], pnl_usd: float) -> None:
    metrics["trades"] = int(metrics.get("trades", 0)) + 1
    if float(pnl_usd) > 0.0:
        metrics["wins"] = int(metrics.get("wins", 0)) + 1
    metrics["total_pnl_usd"] = float(metrics.get("total_pnl_usd", 0.0)) + float(pnl_usd)
    recent = list(metrics.get("recent_pnl_usd", []))
    recent.append(float(pnl_usd))
    window = max(5, int(cfg.COPY_WALLET_PERFORMANCE_WINDOW_TRADES))
    metrics["recent_pnl_usd"] = recent[-window:]


def record_copy_exit(*, exit_price_usd: float, exit_notional_usd: float) -> list[dict[str, float | str]]:
    """Close copy positions FIFO and return realized wallet PnL rows."""
    if float(exit_price_usd) <= 0.0 or float(exit_notional_usd) <= 0.0:
        return []
    store = _load_store()
    opens = list(store.get("open_positions", []))
    if not opens:
        return []
    remaining = float(exit_notional_usd)
    next_open: list[dict[str, Any]] = []
    closed: list[dict[str, float | str]] = []
    for pos in opens:
        if remaining <= 0.0:
            next_open.append(pos)
            continue
        wallet = str(pos.get("wallet", "")).strip()
        entry = float(pos.get("entry_price_usd", 0.0) or 0.0)
        notion = float(pos.get("notional_usd", 0.0) or 0.0)
        if not wallet or notion <= 0.0:
            continue
        close_notional = min(notion, remaining)
        remaining -= close_notional
        pnl = 0.0
        if entry > 0.0:
            pnl = close_notional * ((float(exit_price_usd) - entry) / entry)
        metrics = _wallet_metrics(store, wallet)
        _apply_wallet_pnl(metrics, pnl)
        closed.append({"wallet": wallet, "pnl_usd": float(pnl), "notional_usd": float(close_notional)})
        if notion > close_notional + 1e-9:
            pos["notional_usd"] = notion - close_notional
            next_open.append(pos)
    store["open_positions"] = next_open
    _save_store(store)
    return closed


def wallet_health(wallet: str) -> dict[str, float | bool]:
    store = _load_store()
    metrics = _wallet_metrics(store, str(wallet).strip())
    recent = [float(x) for x in list(metrics.get("recent_pnl_usd", []))]
    trades = int(metrics.get("trades", 0))
    wins = int(metrics.get("wins", 0))
    avg_pnl = (sum(recent) / len(recent)) if recent else 0.0
    win_rate = (float(wins) / float(trades)) if trades > 0 else 0.0
    min_trades = max(3, int(cfg.COPY_WALLET_PERFORMANCE_MIN_TRADES))
    poor_win_rate = float(cfg.COPY_WALLET_PERFORMANCE_POOR_WINRATE)
    poor_avg = float(cfg.COPY_WALLET_PERFORMANCE_POOR_AVG_PNL_USD)
    deprioritize = trades >= min_trades and win_rate < poor_win_rate and avg_pnl < poor_avg
    multiplier = float(cfg.COPY_WALLET_PERFORMANCE_PENALTY_MULTIPLIER) if deprioritize else 1.0
    return {
        "trades": float(trades),
        "win_rate": win_rate,
        "avg_pnl_usd": avg_pnl,
        "deprioritize": deprioritize,
        "allocation_multiplier": max(0.1, min(1.0, multiplier)),
    }
