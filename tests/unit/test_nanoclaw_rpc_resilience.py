import time

import nanoclaw.config as nc_cfg


def _reset_rpc_state() -> None:
    nc_cfg._RPC_LAST_SUCCESS = None
    nc_cfg._RPC_LAST_SUCCESS_TS = 0.0
    nc_cfg._RPC_ENDPOINT_FAILURE_STREAK.clear()
    nc_cfg._RPC_ENDPOINT_COOLDOWN_UNTIL.clear()
    nc_cfg._RPC_CHAIN_LOGGED = False


def test_order_rpc_endpoints_prefers_last_success(monkeypatch):
    _reset_rpc_state()
    nc_cfg.record_rpc_success("https://polygon-rpc.com")
    ordered = nc_cfg.order_rpc_endpoints(
        ["https://1rpc.io/matic", "https://polygon-rpc.com", "https://rpc.ankr.com/polygon"]
    )
    assert ordered[0] == "https://polygon-rpc.com"


def test_rpc_endpoint_enters_cooldown_after_three_failures(monkeypatch):
    _reset_rpc_state()
    ep = "https://polygon-rpc.com"
    for _ in range(3):
        nc_cfg.record_rpc_failure(ep)
    assert nc_cfg.rpc_endpoint_in_cooldown(ep) is True


def test_connect_web3_recovery_pass_after_cooldown(monkeypatch):
    _reset_rpc_state()
    calls: list[str] = []

    def _fake_connect_one(endpoint: str, *, timeout: int):
        calls.append(endpoint)
        if len(calls) <= 3:
            raise RuntimeError("temporary down")
        return object()

    monkeypatch.setattr(nc_cfg, "_connect_one", _fake_connect_one)
    monkeypatch.setattr(nc_cfg, "_RPC_CONNECT_ATTEMPTS", 1)
    monkeypatch.setattr(nc_cfg, "_RPC_FAILURES_BEFORE_COOLDOWN", 1)
    monkeypatch.setattr(nc_cfg, "_RPC_ENDPOINT_COOLDOWN_SEC", 0.05)
    monkeypatch.setattr(nc_cfg, "_RPC_RECOVERY_PASS_DELAY_SEC", 0.05)

    nc_cfg.connect_web3(urls=["https://polygon-rpc.com"])
    assert len(calls) >= 4
