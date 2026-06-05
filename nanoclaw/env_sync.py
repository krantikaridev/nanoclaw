from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

# Explicitly excluded from value mirroring (always blanked in .env.example).
# Keep this list short and reviewable.
ENV_SYNC_EXCLUDED_KEYS = (
    "POLYGON_PRIVATE_KEY",
    "PRIVATE_KEY",
    "ANKR_RPC_KEY",
    "TELEGRAM_BOT_TOKEN",
    "GROK_API_KEY",
    "XAI_API_KEY",
    "ONEINCH_API_KEY",
    "INCH_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

_EXCLUDED_KEYS_SET = frozenset(ENV_SYNC_EXCLUDED_KEYS)
# ``nanoenv_apply`` / ``nanoup`` env sync only merges ``.env`` — never ``control.json``.
# Operator runtime JSON is listed in ``nanoclaw.runtime_state.NANOUP_PRESERVE_RUNTIME_FILES``.

ENV_APPLY_PRESERVE_KEYS = (
    *ENV_SYNC_EXCLUDED_KEYS,
    "TELEGRAM_CHAT_ID",
    # Operator toggles on VM (template defaults must not override stage decisions on nanoup).
    "ALLOW_HIGH_RISK_LOSS_CUT_XSIGNAL",
    "ALLOW_REDUCED_HIGH_RISK_XSIGNAL",
    "X_SIGNAL_HONOR_FULL_BLOCKLIST",
    "MAIN_STRATEGY_PNL_RECOVERY_MODE",
    "PNL_RECOVERY_MODE",
    "EXTERNAL_AUTO_PAUSE_ENABLED",
    "EXTERNAL_RPC_PAUSE_ENABLED",
    "EXTERNAL_AUTO_GREEN_HOURS",
    "EXTERNAL_AUTO_SESSION_MIN_PCT",
    "EXTERNAL_AUTO_WINDOW_MIN_PCT",
    "EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_ENABLED",
    "EXTERNAL_AUTO_UNPAUSE_HYSTERESIS_TICKS",
    "EXTERNAL_AUTO_UNPAUSE_WINDOW_BUFFER_PCT",
    "EXTERNAL_AUTO_UNPAUSE_REQUIRE_DUAL_WINDOW",
    "EXTERNAL_AUTO_UNPAUSE_SHORT_HOURS",
    "PLAY_BUDGET_ENABLED",
    "PLAY_BUDGET_MAX_FILLS_PER_UTC_DAY",
    "PLAY_BUDGET_TOTAL_USD_CEILING",
    "X_SIGNAL_NEGATIVE_WINDOW_CAP_ENABLED",
    "X_SIGNAL_NEGATIVE_WINDOW_CAP_HOURS",
    "X_SIGNAL_NEGATIVE_WINDOW_MAX_TRADE_USD",
    "OPERATING_RESERVE_ENABLED",
    "OPERATING_RESERVE_PCT",
    "OPERATING_RESERVE_TIERED_EXEMPT_ENABLED",
    "STAGE_SEED_USD",
    "STAGE_SEED_AUTO_SYNC_ENABLED",
    "STAGE_SEED_AUTO_SYNC_EMA_DAYS",
    "STAGE_SEED_AUTO_SYNC_MIN_USD",
    "OPEX_MONTHLY_USD",
    "OPEX_CURSOR_MONTHLY_USD",
    "OPEX_GROK_MONTHLY_USD",
    "OPEX_HOSTING_MONTHLY_USD",
    "OPEX_RUNWAY_ALERT_DAYS",
    "OPEX_RUNWAY_TELEGRAM_ENABLED",
    "OPEX_RUNWAY_AUTO_CHECK_ENABLED",
    "OPEX_RUNWAY_AUTO_CHECK_INTERVAL_HOURS",
    "FE_USD_FALLBACK_REFRESH_ENABLED",
    "FE_USD_FALLBACK_MAX_STALE_PCT",
    "FE_USD_FALLBACK_MIN_LIVE_USD",
    "FE_STABLE_RUNWAY_TIERED_ENABLED",
    "FE_STABLE_RUNWAY_TIERED_MIN_SIGNAL",
    "FE_STABLE_RUNWAY_TIERED_MAX_NOTIONAL_USD",
    "FE_STABLE_RUNWAY_TIERED_COOLDOWN_ENABLED",
    "FE_STABLE_RUNWAY_TIERED_COOLDOWN_HOURS",
    "FE_STABLE_RUNWAY_TIERED_COOLDOWN_AFTER_REBUILD",
    "PNL_FLOW_TAG_ENABLED",
    "PNL_FLOW_STEP_MIN_USD",
    "PNL_FLOW_LOOKBACK_HOURS",
    "PNL_FLOW_ONCHAIN_ENABLED",
    "PNL_FLOW_ONCHAIN_LOOKBACK_HOURS",
    "PNL_FLOW_WALLET",
    "PNL_FLOW_AUTO_SYNC_ENABLED",
    "PNL_FLOW_AUTO_SYNC_INTERVAL_HOURS",
    "PNL_ADVERSE_DAY_ENABLED",
    "PNL_ADVERSE_DAY_WINDOW_HOURS",
    "PNL_ADVERSE_DAY_MIN_FILLS",
    "GAS_USD_EST_PER_FILL",
    "ADVERSE_CHURN_GUARD_ENABLED",
    "ADVERSE_CHURN_GUARD_FILL_MULT",
    "DRAWDOWN_THROTTLE_ENABLED",
    "DRAWDOWN_THROTTLE_WINDOW_HOURS",
    "DRAWDOWN_THROTTLE_TRIGGER_PCT",
    "DRAWDOWN_THROTTLE_NOTIONAL_MULT",
    "FE_STABLE_RUNWAY_DERISK_ENABLED",
    "FE_STABLE_RUNWAY_DERISK_MIN_FE_SHARE",
    "FE_STABLE_RUNWAY_DERISK_MAX_WMATIC_USD",
    "WINDOW_STRESS_DERISK_ENABLED",
    "WINDOW_STRESS_DERISK_MIN_FE_SHARE",
    "WINDOW_STRESS_DERISK_MAX_WMATIC_USD",
    "MAIN_STRATEGY_HIGH_STABLE_WMATIC_ROTATION_ENABLED",
    "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_STABLE_USD",
    "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_NOTIONAL_USD",
    "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MIN_SIGNAL",
    "MAIN_STRATEGY_HIGH_STABLE_WMATIC_MAX_FE_SHARE",
    # Never clobber custody / trading identity when applying the template (template may hold a placeholder).
    "WALLET",
    # Preserve stage-specific RPC runtime selection when applying template.
    "RPC_ENDPOINTS",
    "RPC",
    "RPC_URL",
    "WEB3_PROVIDER_URI",
    "RPC_FALLBACKS",
)
# Always take template value on nanoup — even if an older preserve list or --preserve-key included these.
ENV_APPLY_FORCE_TEMPLATE_KEYS = (
    "MIN_POL_FOR_GAS",
)
_ENV_ASSIGNMENT_RE = re.compile(r"^([^\s=#]+)\s*=\s*(.*)$")
_ENV_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def is_excluded_env_key(key: str) -> bool:
    k = str(key or "").strip()
    if k in _EXCLUDED_KEYS_SET:
        return True
    ku = k.upper()
    # Defensive redaction for newly added secrets that follow normal naming.
    return ku.endswith("_PRIVATE_KEY") or ku.endswith("_SECRET") or ku.endswith("_API_KEY")


def sanitize_env_line(line: str) -> str:
    raw = line.rstrip("\n")
    if not raw.strip() or raw.lstrip().startswith("#"):
        return raw
    match = _ENV_ASSIGNMENT_RE.match(raw)
    if not match:
        return raw
    key, _val = match.group(1), match.group(2)
    if is_excluded_env_key(key):
        return f"{key}="
    return raw


def sanitize_env_content(env_content: str) -> str:
    return "\n".join(sanitize_env_line(line) for line in env_content.splitlines()) + "\n"


def extract_env_keys(content: str) -> set[str]:
    return set(_ENV_KEY_RE.findall(content))


@dataclass(frozen=True)
class EnvSyncDiff:
    missing_in_example: tuple[str, ...]
    extra_in_example: tuple[str, ...]
    content_mismatch: bool


def compute_env_sync_diff(env_content: str, env_example_content: str) -> EnvSyncDiff:
    env_keys = extract_env_keys(env_content)
    example_keys = extract_env_keys(env_example_content)
    sanitized = sanitize_env_content(env_content)
    normalized_example = (
        env_example_content
        if env_example_content.endswith("\n")
        else env_example_content + "\n"
    )
    return EnvSyncDiff(
        missing_in_example=tuple(sorted(env_keys - example_keys)),
        extra_in_example=tuple(sorted(example_keys - env_keys)),
        content_mismatch=(sanitized != normalized_example),
    )


def _parse_env_assignments(content: str) -> tuple[list[str], dict[str, str]]:
    order: list[str] = []
    values: dict[str, str] = {}
    for line in content.splitlines():
        match = _ENV_ASSIGNMENT_RE.match(line.rstrip("\n"))
        if not match:
            continue
        key = str(match.group(1)).strip()
        value = str(match.group(2))
        if key not in values:
            order.append(key)
        values[key] = value
    return order, values


def merge_env_from_example(
    env_content: str,
    env_example_content: str,
    *,
    preserve_keys: Iterable[str] = (),
    keep_extra_keys: bool = False,
) -> str:
    """
    Build runtime `.env` from `.env.example` while preserving selected key values from existing `.env`.

    - Preserves comments/ordering from template.
    - For preserved keys, keeps existing `.env` value when present.
    - Optionally appends keys that exist only in `.env` (`keep_extra_keys=True`).
    """
    preserve_set = {str(key).strip() for key in preserve_keys if str(key).strip()}
    force_template_set = {str(key).strip() for key in ENV_APPLY_FORCE_TEMPLATE_KEYS if str(key).strip()}
    current_order, current_values = _parse_env_assignments(env_content)
    merged_lines: list[str] = []
    template_keys_seen: set[str] = set()

    for line in env_example_content.splitlines():
        match = _ENV_ASSIGNMENT_RE.match(line.rstrip("\n"))
        if not match:
            merged_lines.append(line.rstrip("\n"))
            continue
        key = str(match.group(1)).strip()
        template_value = str(match.group(2))
        template_keys_seen.add(key)
        if (
            key not in force_template_set
            and key in preserve_set
            and key in current_values
        ):
            merged_lines.append(f"{key}={current_values[key]}")
            continue
        merged_lines.append(f"{key}={template_value}")

    if keep_extra_keys:
        extras = [k for k in current_order if k not in template_keys_seen]
        if extras:
            if merged_lines and merged_lines[-1].strip():
                merged_lines.append("")
            merged_lines.append("# --- Extra keys kept from existing .env ---")
            for key in extras:
                merged_lines.append(f"{key}={current_values[key]}")

    return "\n".join(merged_lines) + "\n"
