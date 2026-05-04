from __future__ import annotations

from dataclasses import dataclass
import re

# Explicitly excluded from value mirroring (always blanked in .env.example).
# Keep this list short and reviewable.
ENV_SYNC_EXCLUDED_KEYS = (
    "POLYGON_PRIVATE_KEY",
    "PRIVATE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "GROK_API_KEY",
    "XAI_API_KEY",
    "ONEINCH_API_KEY",
    "INCH_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

_EXCLUDED_KEYS_SET = frozenset(ENV_SYNC_EXCLUDED_KEYS)
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
