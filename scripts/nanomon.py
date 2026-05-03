#!/usr/bin/env python3
"""Compact nanoclaw status: tail log, colored highlights, trade summary, live USDC."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _stream_log_tail(path: Path, *, stat_cap: int, tail_n: int) -> tuple[list[str], list[str]]:
    """Single pass: keep last ``max(stat_cap, tail_n)`` lines (bounded memory)."""
    cap = max(stat_cap, tail_n, 1)
    dq: deque[str] = deque(maxlen=cap)
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                dq.append(raw.rstrip("\n"))
    except OSError:
        return [], []
    lines = list(dq)
    stats_lines = lines[-stat_cap:] if len(lines) > stat_cap else lines
    tail = lines[-tail_n:] if len(lines) > tail_n else lines
    return stats_lines, tail


def _ansi(enabled: bool) -> tuple[str, str, str, str, str]:
    if not enabled:
        return ("", "", "", "", "")
    return (
        "\033[1m",
        "\033[92m",  # green
        "\033[91m",  # red
        "\033[93m",  # yellow
        "\033[0m",  # reset
    )


def _colorize_line(line: str, bold: str, g: str, r: str, y: str, reset: str) -> str:
    s = line.rstrip("\n")
    low = s.lower()
    if any(
        x in low
        for x in (
            "swap confirmed",
            "swap executed successfully",
            "trade_attribution tx=0x",
            "✅ swap",
            "✅ approve confirmed",
            "✅ real tx hash",
        )
    ):
        return f"{g}{s}{reset}"
    if any(
        x in low
        for x in (
            "❌",
            "failed on-chain",
            "swap failed",
            "error in approve_and_swap",
            "after fallback retry",
            "on-chain swap reverted",
            "approve failed",
        )
    ):
        return f"{r}{s}{reset}"
    if any(
        x in low
        for x in (
            "warning",
            "⚠",
            "skipped",
            "trade skipped",
            "block:",
            "plan failed",
        )
    ):
        return f"{y}{s}{reset}"
    return s


def _attribution_success_line(ln: str) -> bool:
    """Case-insensitive: trade attribution with a real tx hash (not pending)."""
    low = ln.lower()
    return "trade_attribution" in low and "tx=0x" in low and "tx=pending" not in low


def _parse_log_stats(lines: list[str]) -> dict:
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")

    attempted = sum(1 for ln in lines if "swap EXEC |" in ln)

    attr_ok = sum(1 for ln in lines if _attribution_success_line(ln))
    legacy_ok = sum(
        1
        for ln in lines
        if "swap executed successfully!" in ln.lower() or "✅ swap confirmed" in ln.lower()
    )
    success = attr_ok if attr_ok > 0 else legacy_ok

    fail = 0
    for line in lines:
        l = line.lower()
        if any(
            x in l
            for x in (
                "failed on-chain",
                "swap failed —",
                "after fallback retry",
                "error in approve_and_swap",
            )
        ):
            fail += 1

    last_ok_ts: str | None = None
    for line in reversed(lines):
        l = line.lower()
        ok_line = (
            _attribution_success_line(line)
            or "swap executed successfully!" in l
            or "✅ swap confirmed" in l
        )
        if not ok_line:
            continue
        m = ts_re.match(line)
        if m:
            last_ok_ts = m.group(1).replace("T", " ")
        else:
            last_ok_ts = "(time unknown)"
        break

    return {
        "attempted": attempted,
        "success": success,
        "fail": fail,
        "last_ok": last_ok_ts or "-",
    }


def _usdc_from_log(lines: list[str]) -> str | None:
    """Best-effort USDC from recent cron lines (e.g. ``USDC=$12.34`` in balance banners)."""
    for line in reversed(lines):
        m = re.search(r"USDC=\$([0-9]*\.?[0-9]+)", line)
        if m:
            return m.group(1)
        m2 = re.search(r"\bUSDC:\s*([0-9]*\.?[0-9]+)\b", line)
        if m2:
            return m2.group(1)
    return None


def _usdc_balance(root: Path, stats_lines: list[str], *, timeout_s: float = 8.0) -> str:
    """Isolated subprocess so ``clean_swap`` import banners do not pollute this TTY."""
    root_s = str(root.resolve())
    snippet = (
        "import sys; "
        f"sys.path.insert(0, {json.dumps(root_s)}); "
        "from clean_swap import get_balances; "
        "print(float(get_balances().usdc))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=root_s,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=os.environ.copy(),
        )
        if proc.returncode != 0:
            alt = _usdc_from_log(stats_lines)
            return alt if alt is not None else "(chain read failed; no USDC in log)"
        out = (proc.stdout or "").strip().splitlines()
        if not out:
            alt = _usdc_from_log(stats_lines)
            return alt if alt is not None else "(empty)"
        return f"{float(out[-1]):.2f}"
    except subprocess.TimeoutExpired:
        alt = _usdc_from_log(stats_lines)
        return alt if alt is not None else "(RPC timeout)"
    except Exception as ex:
        alt = _usdc_from_log(stats_lines)
        return alt if alt is not None else f"(unavailable: {type(ex).__name__})"


def main() -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="Nanoclaw compact monitor (log tail + trade summary).")
    p.add_argument("--tail", type=int, default=18, help="Lines of real_cron.log to show (default 18).")
    p.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Log file path (default: ./real_cron.log then repo root).",
    )
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    p.add_argument(
        "--no-chain",
        action="store_true",
        help="Skip live USDC balance (avoids RPC; use when .env/RPC unavailable).",
    )
    args = p.parse_args()

    root = _repo_root()
    log_path = args.log
    if log_path is None:
        cand = Path.cwd() / "real_cron.log"
        log_path = cand if cand.is_file() else root / "real_cron.log"

    use_color = not args.no_color and sys.stdout.isatty() and os.getenv("NO_COLOR", "") == ""
    bold, gr, rd, yl, reset = _ansi(use_color)

    print(f"{bold}=== nanomon {log_path.name} ==={reset}")

    stats_lines: list[str] = []
    tail: list[str] = []
    if log_path.is_file():
        tail_n = max(1, min(args.tail, 200))
        stats_lines, tail = _stream_log_tail(log_path, stat_cap=8000, tail_n=tail_n)
        if not tail and not stats_lines:
            print(f"{rd}Could not read log: {log_path}{reset}")
    else:
        print(f"{yl}Log not found: {log_path}{reset}")

    st = _parse_log_stats(stats_lines)
    usdc = "(skipped --no-chain)" if args.no_chain else _usdc_balance(root, stats_lines)

    print(f"{bold}--- LAST TRADE SUMMARY ---{reset}")
    print(f"  total swap attempts (recent log window): {st['attempted']}")
    print(f"  success signals (attribution / confirmed): {gr}{st['success']}{reset}")
    print(f"  on-chain failure signals (log): {rd}{st['fail']}{reset}")
    print(f"  last successful trade time: {st['last_ok']}")
    print(f"  current USDC balance: ${usdc}")
    print(f"{bold}--- LAST {len(tail)} LINES ---{reset}")
    for line in tail:
        print(_colorize_line(line, bold, gr, rd, yl, reset))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
