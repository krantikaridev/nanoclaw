from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _load_script_module() -> dict:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "nanoenv_apply.py"
    return runpy.run_path(str(script_path))


def test_nanoenv_apply_default_preserve_keys_include_rpc_and_secrets():
    mod = _load_script_module()
    keys = set(mod["_default_preserve_keys"]())
    assert "POLYGON_PRIVATE_KEY" in keys
    assert "RPC_ENDPOINTS" in keys
    assert "RPC" in keys
    assert "RPC_URL" in keys
    assert "WEB3_PROVIDER_URI" in keys
    assert "RPC_FALLBACKS" in keys


def test_nanoenv_apply_returns_error_when_template_missing(monkeypatch, capsys, tmp_path):
    mod = _load_script_module()
    main = mod["main"]
    env_file = tmp_path / ".env"
    missing_template = tmp_path / ".env.example"
    argv = [
        "nanoenv_apply.py",
        "--env-file",
        str(env_file),
        "--template-file",
        str(missing_template),
        "--write",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    rc = main()
    captured = capsys.readouterr()

    assert rc == 2
    assert "template file not found" in captured.err


def test_nanoenv_apply_stdout_mode_outputs_merged_result(monkeypatch, capsys, tmp_path):
    mod = _load_script_module()
    main = mod["main"]
    env_file = tmp_path / ".env"
    template_file = tmp_path / ".env.example"
    env_file.write_text("POLYGON_PRIVATE_KEY=secret\nRPC_ENDPOINTS=https://stage-rpc\nA=1\n", encoding="utf-8")
    template_file.write_text("POLYGON_PRIVATE_KEY=\nRPC_ENDPOINTS=https://template-rpc\nA=2\n", encoding="utf-8")
    argv = [
        "nanoenv_apply.py",
        "--env-file",
        str(env_file),
        "--template-file",
        str(template_file),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    rc = main()
    captured = capsys.readouterr()

    assert rc == 0
    assert "POLYGON_PRIVATE_KEY=secret\n" in captured.out
    assert "RPC_ENDPOINTS=https://stage-rpc\n" in captured.out
    assert "A=2\n" in captured.out
    assert captured.err == ""
    # stdout mode must not modify existing env file.
    assert env_file.read_text(encoding="utf-8") == "POLYGON_PRIVATE_KEY=secret\nRPC_ENDPOINTS=https://stage-rpc\nA=1\n"


def test_nanoenv_apply_write_mode_creates_backup_and_preserves_default_keys(monkeypatch, capsys, tmp_path):
    mod = _load_script_module()
    main = mod["main"]
    env_file = tmp_path / ".env"
    template_file = tmp_path / ".env.example"
    env_file.write_text(
        "POLYGON_PRIVATE_KEY=very-secret\n"
        "RPC_ENDPOINTS=https://stage-rpc\n"
        "X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS=5\n",
        encoding="utf-8",
    )
    template_file.write_text(
        "POLYGON_PRIVATE_KEY=\n"
        "RPC_ENDPOINTS=https://template-rpc\n"
        "X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS=2\n",
        encoding="utf-8",
    )
    argv = [
        "nanoenv_apply.py",
        "--env-file",
        str(env_file),
        "--template-file",
        str(template_file),
        "--write",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    rc = main()
    captured = capsys.readouterr()
    new_env = env_file.read_text(encoding="utf-8")

    assert rc == 0
    assert "backup created:" in captured.err
    backups = list(tmp_path.glob(".env.bak.*"))
    assert len(backups) == 1
    assert "POLYGON_PRIVATE_KEY=very-secret\n" in new_env
    assert "RPC_ENDPOINTS=https://stage-rpc\n" in new_env
    assert "X_SIGNAL_ONCHAIN_USDC_RETRY_ATTEMPTS=2\n" in new_env


def test_nanoenv_apply_preserve_key_flag_keeps_custom_key(monkeypatch, tmp_path):
    mod = _load_script_module()
    main = mod["main"]
    env_file = tmp_path / ".env"
    template_file = tmp_path / ".env.example"
    env_file.write_text("CUSTOM_KEEP=stage\nA=1\n", encoding="utf-8")
    template_file.write_text("CUSTOM_KEEP=template\nA=2\n", encoding="utf-8")
    argv = [
        "nanoenv_apply.py",
        "--env-file",
        str(env_file),
        "--template-file",
        str(template_file),
        "--write",
        "--preserve-key",
        "CUSTOM_KEEP",
        "--no-backup",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    rc = main()
    new_env = env_file.read_text(encoding="utf-8")

    assert rc == 0
    assert "CUSTOM_KEEP=stage\n" in new_env
    assert "A=2\n" in new_env
