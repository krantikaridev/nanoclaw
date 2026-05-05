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
ENV_APPLY_PRESERVE_KEYS = (
    *ENV_SYNC_EXCLUDED_KEYS,
    "TELEGRAM_CHAT_ID",
    # Never clobber custody / trading identity when applying the template (template may hold a placeholder).
    "WALLET",
    # Preserve stage-specific RPC runtime selection when applying template.
    "RPC_ENDPOINTS",
    "RPC",
    "RPC_URL",
    "WEB3_PROVIDER_URI",
    "RPC_FALLBACKS",
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
        if key in preserve_set and key in current_values:
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
