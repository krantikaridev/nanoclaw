from __future__ import annotations

import pytest

from nanoclaw.rpc_probe import (
    any_endpoint_healthy,
    format_probe_report,
    probe_rpc_chain,
    redact_rpc_url,
)


def test_redact_rpc_url_hides_key() -> None:
    url = "https://rpc.ankr.com/polygon/d67901a56c5bbfe443952d886f64de1930088dfd1427764aa37124c24699f494"
    assert redact_rpc_url(url) == "https://rpc.ankr.com/polygon/***"
    assert redact_rpc_url("https://polygon-rpc.com") == "https://polygon-rpc.com"


def test_probe_rpc_chain_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake_probe(url: str, *, timeout: int = 12):
        from nanoclaw.rpc_probe import RpcEndpointProbe

        calls.append(url)
        if "good" in url:
            return RpcEndpointProbe(
                url=url,
                ok=True,
                chain_id=137,
                block_number=99,
                latency_ms=50.0,
                error=None,
            )
        return RpcEndpointProbe(
            url=url,
            ok=False,
            chain_id=None,
            block_number=None,
            latency_ms=10.0,
            error="401 Unauthorized",
        )

    monkeypatch.setattr("nanoclaw.rpc_probe.probe_rpc_endpoint", _fake_probe)
    probes = probe_rpc_chain(["https://bad.example", "https://good.example"], timeout=5)
    assert len(probes) == 2
    assert any_endpoint_healthy(probes) is True
    report = format_probe_report(probes)
    assert "1/2 healthy" in report
    assert "OK" in report
    assert "FAIL" in report


def test_probe_configured_endpoints_uses_default_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanoclaw.config.default_json_rpc_url",
        lambda: ["https://polygon-rpc.com"],
    )

    def _ok(url: str, *, timeout: int = 12):
        from nanoclaw.rpc_probe import RpcEndpointProbe

        return RpcEndpointProbe(
            url=url,
            ok=True,
            chain_id=137,
            block_number=123,
            latency_ms=40.0,
            error=None,
        )

    monkeypatch.setattr("nanoclaw.rpc_probe.probe_rpc_endpoint", _ok)

    from nanoclaw.rpc_probe import probe_configured_endpoints

    probes = probe_configured_endpoints(timeout=5)
    assert len(probes) == 1
    assert probes[0].ok is True
