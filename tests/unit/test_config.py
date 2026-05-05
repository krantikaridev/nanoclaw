import config


def test_reconcile_fixed_trade_min_raises_strategy_floor_to_global_minimum():
    assert config.reconcile_fixed_trade_min(6.5, 5.0) == 6.5


def test_reconcile_fixed_trade_min_keeps_higher_strategy_floor():
    assert config.reconcile_fixed_trade_min(6.5, 9.0) == 9.0


def test_env_float_uses_default_when_value_is_empty(monkeypatch):
    monkeypatch.setenv("TEST_ENV_FLOAT_EMPTY", "")
    assert config.env_float("TEST_ENV_FLOAT_EMPTY", 5.0) == 5.0


def test_env_int_uses_default_when_value_is_empty(monkeypatch):
    monkeypatch.setenv("TEST_ENV_INT_EMPTY", "")
    assert config.env_int("TEST_ENV_INT_EMPTY", 7) == 7


def test_env_bool_uses_default_when_value_is_empty(monkeypatch):
    monkeypatch.setenv("TEST_ENV_BOOL_EMPTY", "")
    assert config.env_bool("TEST_ENV_BOOL_EMPTY", True) is True


def test_parse_csv_urls_trims_and_drops_empty_entries():
    out = config.parse_csv_urls(" https://a , ,https://b,, ")
    assert out == ["https://a", "https://b"]


def test_merge_unique_urls_preserves_first_seen_order():
    merged = config.merge_unique_urls(
        ["https://a", "https://b"],
        ["https://b", "https://c"],
        ["", "   ", "https://a", "https://d"],
    )
    assert merged == ["https://a", "https://b", "https://c", "https://d"]


def test_get_resolved_key_prefers_polygon_private_key(monkeypatch):
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "polygon-key")
    monkeypatch.setenv("PRIVATE_KEY", "legacy-key")
    assert config.get_resolved_key() == "polygon-key"


def test_get_resolved_key_falls_back_to_legacy_private_key(monkeypatch):
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("PRIVATE_KEY", "legacy-key")
    assert config.get_resolved_key() == "legacy-key"


def test_normalize_private_key_hex_strips_whitespace_and_bom() -> None:
    body = "a" * 64
    assert config.normalize_private_key_hex(f"  0x{body}  ") == "0x" + body.lower()
    assert config.normalize_private_key_hex(f"\ufeff0x{body}") == "0x" + body.lower()
    assert config.normalize_private_key_hex(f"{body}\n\r") == "0x" + body.lower()


def test_normalize_private_key_hex_adds_0x_for_bare_64_hex() -> None:
    body = "b" * 64
    assert config.normalize_private_key_hex(body) == "0x" + body.lower()


def test_normalize_private_key_hex_leaves_placeholder_strings() -> None:
    assert config.normalize_private_key_hex("polygon-key") == "polygon-key"


def test_normalize_private_key_hex_rejects_wrong_hex_length() -> None:
    try:
        config.normalize_private_key_hex("a" * 66)
    except ValueError as exc:
        assert "66" in str(exc) and "64" in str(exc)
    else:
        raise AssertionError("expected ValueError for 66 nibbles")


def test_resolve_private_key_prefers_env_over_function_arg(monkeypatch):
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", "polygon-key")
    monkeypatch.setenv("PRIVATE_KEY", "legacy-key")
    key, source = config.resolve_private_key("arg-key")
    assert key == "polygon-key"
    assert source == "POLYGON_PRIVATE_KEY"


def test_resolve_private_key_normalizes_env_hex(monkeypatch) -> None:
    body = "c" * 64
    monkeypatch.setenv("POLYGON_PRIVATE_KEY", body + "\n")
    key, source = config.resolve_private_key()
    assert source == "POLYGON_PRIVATE_KEY"
    assert key == "0x" + body.lower()


def test_resolve_private_key_uses_function_arg_when_env_missing(monkeypatch):
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    key, source = config.resolve_private_key("arg-key")
    assert key == "arg-key"
    assert source == "function_arg"


def test_resolve_private_key_requires_uses_function_arg_when_provided(monkeypatch):
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    key, source = config.resolve_private_key("arg-key", require=True)
    assert key == "arg-key"
    assert source == "function_arg"


def test_resolve_private_key_raises_when_required_and_missing(monkeypatch):
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    try:
        config.resolve_private_key(require=True)
    except config.MissingPrivateKeyError as exc:
        assert "POLYGON_PRIVATE_KEY" in str(exc)
        assert "PRIVATE_KEY" in str(exc)
    else:
        raise AssertionError("Expected MissingPrivateKeyError when required key is missing")
