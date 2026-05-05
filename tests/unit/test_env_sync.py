from nanoclaw.env_sync import (
    ENV_APPLY_PRESERVE_KEYS,
    compute_env_sync_diff,
    merge_env_from_example,
    sanitize_env_content,
)
from pathlib import Path

import pytest


def test_sanitize_env_content_blanks_excluded_keys_and_keeps_non_secret_values():
    env = (
        "POLYGON_PRIVATE_KEY=abc123\n"
        "PRIVATE_KEY=def456\n"
        "ANKR_RPC_KEY=secret-token\n"
        "TELEGRAM_CHAT_ID=123456789\n"
        "SWAP_SLIPPAGE_BPS=80\n"
        "MIN_TRADE_USD=22\n"
    )
    out = sanitize_env_content(env)
    assert "POLYGON_PRIVATE_KEY=\n" in out
    assert "PRIVATE_KEY=\n" in out
    assert "ANKR_RPC_KEY=\n" in out
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


def test_merge_env_from_example_preserves_selected_secret_keys():
    current = (
        "POLYGON_PRIVATE_KEY=super-secret\n"
        "RPC_ENDPOINTS=https://old-rpc\n"
        "X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS=5\n"
    )
    template = (
        "POLYGON_PRIVATE_KEY=\n"
        "RPC_ENDPOINTS=https://new-rpc,https://backup-rpc\n"
        "X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS=2\n"
    )

    out = merge_env_from_example(
        current,
        template,
        preserve_keys=("POLYGON_PRIVATE_KEY",),
        keep_extra_keys=False,
    )

    assert "POLYGON_PRIVATE_KEY=super-secret\n" in out
    assert "RPC_ENDPOINTS=https://new-rpc,https://backup-rpc\n" in out
    assert "X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS=2\n" in out


def test_merge_env_from_example_preserves_wallet_from_existing_env():
    current = "WALLET=0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n" "SWAP_SLIPPAGE_BPS=80\n"
    template = "WALLET=0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n" "SWAP_SLIPPAGE_BPS=99\n"

    out = merge_env_from_example(
        current,
        template,
        preserve_keys=("WALLET",),
        keep_extra_keys=False,
    )

    assert "WALLET=0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n" in out
    assert "SWAP_SLIPPAGE_BPS=99\n" in out


def test_merge_env_from_example_appends_extra_keys_when_requested():
    current = "A=old\nEXTRA_KEY=123\n"
    template = "A=new\nB=2\n"

    out = merge_env_from_example(
        current,
        template,
        preserve_keys=(),
        keep_extra_keys=True,
    )

    assert "A=new\n" in out
    assert "B=2\n" in out
    assert "# --- Extra keys kept from existing .env ---\n" in out
    assert "EXTRA_KEY=123\n" in out


def test_env_apply_preserve_keys_include_rpc_runtime_keys():
    keys = set(ENV_APPLY_PRESERVE_KEYS)
    assert "WALLET" in keys
    assert "MIN_POL_FOR_GAS" in keys
    assert "ANKR_RPC_KEY" in keys
    assert "RPC_ENDPOINTS" in keys
    assert "RPC" in keys
    assert "RPC_URL" in keys
    assert "WEB3_PROVIDER_URI" in keys
    assert "RPC_FALLBACKS" in keys
