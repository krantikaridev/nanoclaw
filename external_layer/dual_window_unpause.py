"""Dual-window gate for auto_unpause — require both 8h and 12h window PASS."""

from __future__ import annotations

from pathlib import Path


def dual_window_unpause_required() -> bool:
    import os

    raw = os.environ.get("EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW")
    if raw is None or not str(raw).strip():
        try:
            import config as cfg

            return bool(getattr(cfg, "EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW", True))
        except Exception:
            return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _unpause_short_hours() -> float:
    import os

    raw = os.environ.get("EXTERNAL_AUTO_UNPAUSE_SHORT_HOURS")
    if raw is None or not str(raw).strip():
        try:
            import config as cfg

            return float(getattr(cfg, "EXTERNAL_AUTO_UNPAUSE_SHORT_HOURS", 8.0))
        except Exception:
            return 8.0
    try:
        return float(str(raw).strip())
    except ValueError:
        return 8.0


def _unpause_long_hours() -> float:
    import os

    raw = os.environ.get("EXTERNAL_AUTO_GREEN_HOURS")
    if raw is None or not str(raw).strip():
        try:
            import config as cfg

            return float(getattr(cfg, "EXTERNAL_AUTO_GREEN_HOURS", 12.0))
        except Exception:
            return 12.0
    try:
        return float(str(raw).strip())
    except ValueError:
        return 12.0


def evaluate_dual_window_unpause(
    root: Path,
    *,
    window_min_pct: float,
    long_hours: float | None = None,
) -> tuple[bool, str]:
    """Return (allowed, detail). SKIP/waived windows do not count as PASS for unpause."""
    from scripts.nano_green import _session_pnl_check, _window_pnl_check

    short_h = _unpause_short_hours()
    long_h = float(long_hours if long_hours is not None else _unpause_long_hours())
    _, _, _, current_total = _session_pnl_check(root, session_min_pct=-999.0)
    checks: list[tuple[float, bool, str]] = []
    for hours in sorted({short_h, long_h}):
        ok, detail = _window_pnl_check(
            root,
            hours=hours,
            window_min_pct=window_min_pct,
            current_total=current_total,
        )
        passed = bool(ok) and str(detail).startswith("PASS")
        checks.append((hours, passed, detail))

    failed = [(h, d) for h, passed, d in checks if not passed]
    if failed:
        h0, d0 = failed[0]
        return False, (
            f"auto_pause | dual-window unpause blocked | {h0:.0f}h below "
            f"{window_min_pct:+.1f}% ({d0.split('|', 1)[-1].strip()})"
        )
    parts = " & ".join(f"{h:.0f}h PASS" for h, _, _ in checks)
    return True, parts
