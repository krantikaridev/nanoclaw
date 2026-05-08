import importlib


def test_modules_signal_imports() -> None:
    # Regression test: ensure `modules.signal` is syntactically valid and importable.
    importlib.import_module("modules.signal")

