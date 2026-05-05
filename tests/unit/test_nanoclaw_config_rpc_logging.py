import nanoclaw.config as nc_cfg


def test_connect_web3_logs_resolved_rpc_chain_once(monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr(nc_cfg, "_RPC_CHAIN_LOGGED", False)

    class _DummyWeb3:
        pass

    calls = {"count": 0}

    def _fake_connect_one(endpoint: str, *, timeout: int):
        _ = (endpoint, timeout)
        calls["count"] += 1
        return _DummyWeb3()

    monkeypatch.setattr(nc_cfg, "_connect_one", _fake_connect_one)

    nc_cfg.connect_web3(urls=["https://rpc-one"])
    nc_cfg.connect_web3(urls=["https://rpc-two"])

    log_lines = [r.getMessage() for r in caplog.records if "Resolved RPC endpoint chain" in r.getMessage()]
    assert len(log_lines) == 1
    assert "https://rpc-one" in log_lines[0]
    assert calls["count"] == 2
