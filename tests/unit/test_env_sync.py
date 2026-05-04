from nanoclaw.env_sync import compute_env_sync_diff, sanitize_env_content
from pathlib import Path

import pytest


def test_sanitize_env_content_blanks_excluded_keys_and_keeps_non_secret_values():
    env = (
        "POLYGON_PRIVATE_KEY=abc123\n"
        "PRIVATE_KEY=def456\n"
        "TELEGRAM_CHAT_ID=123456789\n"
        "SWAP_SLIPPAGE_BPS=80\n"
        "MIN_TRADE_USD=22\n"
    )
    out = sanitize_env_content(env)
    assert "POLYGON_PRIVATE_KEY=\n" in out
    assert "PRIVATE_KEY=\n" in out
    assert "TELEGRAM_CHAT_ID=123456789\n" in out
    assert "SWAP_SLIPPAGE_BPS=80\n" in out
    assert "MIN_TRADE_USD=22\n" in out


def test_compute_env_sync_diff_detects_key_and_content_drift():
    env = "A=1\nB=2\nSECRET_API_KEY=topsecret\n"
    example = "A=1\nC=3\nSECRET_API_KEY=\n"

    diff = compute_env_sync_diff(env, example)

    assert diff.missing_in_example == ("B",)
    assert diff.extra_in_example == ("C",)
    assert diff.content_mismatch is True


def test_repo_env_example_keys_do_not_drift_when_env_exists():
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    env_example_path = repo_root / ".env.example"
    if not env_path.exists():
        pytest.skip(".env not present in this environment")

    diff = compute_env_sync_diff(
        env_path.read_text(encoding="utf-8"),
        env_example_path.read_text(encoding="utf-8"),
    )
    assert diff.missing_in_example == ()
    assert diff.extra_in_example == ()
