from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nanoclaw.pnl_flow_onchain import (
    TRANSFER_EVENT_TOPIC,
    OnchainFlowRecord,
    fetch_transfer_logs,
    merge_onchain_records_into_jsonl,
    run_pnl_flow_sync,
    scrape_onchain_flows,
    wallet_topic_hex,
    _parse_transfer_log,
)
import scripts.pnl_report as pnl_report
from external_layer import pnl_flow_gate as pfg


WALLET = "0x05eF62F48Cf339AA003F1a42E4CbD622FFa1FBe6"
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
OTHER = "0x1111111111111111111111111111111111111111"
BLOCK_TS = datetime(2026, 5, 31, 10, 0, 0, tzinfo=timezone.utc)


def _amount_data(amount_usd: float) -> bytes:
    raw = int(round(amount_usd * 1_000_000))
    return raw.to_bytes(32, byteorder="big")


def _deposit_log(*, tx_hash: str, amount_usd: float, block_number: int = 100) -> dict:
    return {
        "topics": [
            TRANSFER_EVENT_TOPIC,
            "0x" + OTHER.lower().removeprefix("0x").zfill(64),
            wallet_topic_hex(WALLET),
        ],
        "data": _amount_data(amount_usd),
        "transactionHash": tx_hash,
        "blockNumber": block_number,
    }


def _withdraw_log(*, tx_hash: str, amount_usd: float, block_number: int = 101) -> dict:
    return {
        "topics": [
            TRANSFER_EVENT_TOPIC,
            wallet_topic_hex(WALLET),
            "0x" + OTHER.lower().removeprefix("0x").zfill(64),
        ],
        "data": _amount_data(amount_usd),
        "transactionHash": tx_hash,
        "blockNumber": block_number,
    }


def test_wallet_topic_hex_pads_address() -> None:
    assert wallet_topic_hex(WALLET).endswith(WALLET.lower().removeprefix("0x"))


def test_parse_transfer_log_deposit_and_withdraw() -> None:
    dep = _parse_transfer_log(
        _deposit_log(tx_hash="0xabc", amount_usd=18.67),
        wallet=WALLET,
        token_symbol="USDT",
        token_address=USDT,
        block_ts=BLOCK_TS,
    )
    assert dep is not None
    assert dep.kind == "deposit"
    assert dep.amount_usd == pytest.approx(18.67)
    assert dep.tx_hash == "0xabc"

    wd = _parse_transfer_log(
        _withdraw_log(tx_hash="0xdef", amount_usd=10.02),
        wallet=WALLET,
        token_symbol="USDT",
        token_address=USDT,
        block_ts=BLOCK_TS,
    )
    assert wd is not None
    assert wd.kind == "withdraw"
    assert wd.amount_usd == pytest.approx(10.02)


def test_fetch_transfer_logs_chunks_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _fake_get_logs(params: dict) -> list[dict]:
        calls.append(params)
        if params["topics"][1] is None:
            return [_deposit_log(tx_hash="0x1", amount_usd=20.0)]
        return [_withdraw_log(tx_hash="0x2", amount_usd=10.0)]

    in_logs = fetch_transfer_logs(
        _fake_get_logs,
        token_address=USDT,
        wallet=WALLET,
        from_block=0,
        to_block=2500,
        direction="in",
        chunk_blocks=2000,
    )
    out_logs = fetch_transfer_logs(
        _fake_get_logs,
        token_address=USDT,
        wallet=WALLET,
        from_block=0,
        to_block=2500,
        direction="out",
        chunk_blocks=2000,
    )
    assert len(in_logs) == 2  # two chunks for 0..2500
    assert len(out_logs) == 2
    assert calls[0]["topics"][2] == wallet_topic_hex(WALLET)
    assert calls[-1]["topics"][1] == wallet_topic_hex(WALLET)


def test_scrape_onchain_flows_with_mocked_rpc() -> None:
    deposit_tx = "0x" + "a" * 64
    withdraw_tx = "0x" + "b" * 64

    def _get_logs(params: dict) -> list[dict]:
        topics = params["topics"]
        if topics[1] is None:
            return [_deposit_log(tx_hash=deposit_tx, amount_usd=18.67, block_number=500)]
        return [_withdraw_log(tx_hash=withdraw_tx, amount_usd=10.02, block_number=501)]

    def _block_ts(block_num: int) -> datetime | None:
        if block_num == 500:
            return datetime(2026, 5, 31, 9, 0, 0, tzinfo=timezone.utc)
        if block_num == 501:
            return datetime(2026, 5, 31, 11, 0, 0, tzinfo=timezone.utc)
        return None

    records = scrape_onchain_flows(
        wallet=WALLET,
        lookback_hours=168.0,
        min_usd=5.0,
        now_utc=datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc),
        get_logs=_get_logs,
        get_block_timestamp=_block_ts,
        latest_block_number=1000,
        token_addresses=[("USDT", USDT)],
    )
    assert len(records) == 2
    assert records[0].kind == "deposit"
    assert records[0].amount_usd == pytest.approx(18.67)
    assert records[1].kind == "withdraw"
    assert records[1].amount_usd == pytest.approx(10.02)


def test_scrape_onchain_flows_ignores_dust() -> None:
    def _get_logs(params: dict) -> list[dict]:
        return [_deposit_log(tx_hash="0xdust", amount_usd=2.0)]

    records = scrape_onchain_flows(
        wallet=WALLET,
        lookback_hours=24.0,
        min_usd=5.0,
        now_utc=datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc),
        get_logs=_get_logs,
        get_block_timestamp=lambda _b: BLOCK_TS,
        latest_block_number=100,
        token_addresses=[("USDT", USDT)],
    )
    assert records == []


def test_merge_onchain_records_into_jsonl_dedupes_by_tx(tmp_path: Path) -> None:
    path = tmp_path / "pnl_flow_events.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-31T09:00:00+00:00",
                "kind": "deposit",
                "amount_usd": 18.67,
                "source": "onchain",
                "tx_hash": "0xexisting",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    records = [
        OnchainFlowRecord(
            ts=BLOCK_TS,
            kind="deposit",
            amount_usd=18.67,
            tx_hash="0xexisting",
            block_number=1,
            token_symbol="USDT",
            token_address=USDT,
            from_address=OTHER,
            to_address=WALLET,
        ),
        OnchainFlowRecord(
            ts=BLOCK_TS,
            kind="withdraw",
            amount_usd=10.02,
            tx_hash="0xnewwithdraw",
            block_number=2,
            token_symbol="USDT",
            token_address=USDT,
            from_address=WALLET,
            to_address=OTHER,
        ),
    ]
    existing, appended = merge_onchain_records_into_jsonl(records, path)
    assert existing == 1
    assert appended == 1
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    last = json.loads(lines[-1])
    assert last["tx_hash"] == "0xnewwithdraw"
    assert last["source"] == "onchain"


def test_collect_session_flow_events_prefers_onchain_over_heuristic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow_path = tmp_path / "pnl_flow_events.jsonl"
    flow_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-31T10:00:00+00:00",
                "kind": "deposit",
                "amount_usd": 18.67,
                "source": "onchain",
                "tx_hash": "0xonchaindep",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    csv_file = tmp_path / "portfolio_history.csv"
    csv_file.write_text(
        "timestamp,usdt,usdc,total_value\n"
        "2026-05-31T08:00:00+00:00,10,10,100\n"
        "2026-05-31T10:00:00+00:00,28.67,10,118.67\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pnl_report, "PORTFOLIO_HISTORY_FILE", str(csv_file))
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    events = pnl_report.collect_session_flow_events(
        "2026-05-30T00:00:00+00:00",
        now_utc=now,
        manual_path=flow_path,
    )
    assert len(events) == 1
    assert events[0].source == "onchain"
    assert events[0].amount_usd == pytest.approx(18.67)


def test_format_flow_event_tag_onchain_suffix() -> None:
    event = pnl_report.FlowEvent(
        ts=datetime(2026, 5, 31, 10, 0, 0, tzinfo=timezone.utc),
        kind="deposit",
        amount_usd=18.67,
        source="onchain",
        confidence=1.0,
        tx_hash="0xabcdef1234567890",
    )
    tag = pnl_report.format_flow_event_tag(event)
    assert "(on-chain)" in tag
    assert "tx=0xabcdef12" in tag
    assert "deposit +$18.67" in tag


def test_format_flow_adjusted_line_uses_onchain_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow_path = tmp_path / "pnl_flow_events.jsonl"
    flow_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-31T10:00:00+00:00",
                "kind": "deposit",
                "amount_usd": 18.67,
                "source": "onchain",
                "tx_hash": "0xonchaindep",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PNL_FLOW_TAG_ENABLED", "true")
    line = pnl_report.format_flow_adjusted_line(
        19.8,
        100.0,
        "2026-05-30T00:00:00+00:00",
        now_utc=datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc),
        manual_path=flow_path,
    )
    assert line is not None
    assert "Flow-adjusted session PnL: $+1.13 (+1.13%)" in line
    assert "(on-chain)" in line
    assert "deposit +$18.67" in line


def _mock_rpc_get_logs(deposit_tx: str, withdraw_tx: str):
    def _get_logs(params: dict) -> list[dict]:
        topics = params["topics"]
        if topics[1] is None:
            return [_deposit_log(tx_hash=deposit_tx, amount_usd=18.67, block_number=500)]
        return [_withdraw_log(tx_hash=withdraw_tx, amount_usd=10.02, block_number=501)]

    def _block_ts(block_num: int) -> datetime | None:
        if block_num == 500:
            return datetime(2026, 5, 31, 9, 0, 0, tzinfo=timezone.utc)
        if block_num == 501:
            return datetime(2026, 5, 31, 11, 0, 0, tzinfo=timezone.utc)
        return None

    return _get_logs, _block_ts


def test_run_pnl_flow_sync_with_mocked_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PNL_FLOW_ONCHAIN_ENABLED", "true")
    monkeypatch.setenv("PNL_FLOW_WALLET", WALLET)
    deposit_tx = "0x" + "c" * 64
    withdraw_tx = "0x" + "d" * 64
    get_logs, block_ts = _mock_rpc_get_logs(deposit_tx, withdraw_tx)
    jsonl_path = tmp_path / "pnl_flow_events.jsonl"

    result = run_pnl_flow_sync(
        lookback_hours=168.0,
        jsonl_path=jsonl_path,
        get_logs=get_logs,
        get_block_timestamp=block_ts,
        latest_block_number=1000,
        token_addresses=[("USDT", USDT)],
        now_utc=datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result.scraped == 2
    assert result.appended == 2
    assert result.wallet == WALLET
    lines = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2


def test_pnl_flow_gate_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    pfg.reset_pnl_flow_gate_state_for_tests()
    monkeypatch.setenv("PNL_FLOW_AUTO_SYNC_ENABLED", "false")
    pfg.maybe_run_pnl_flow_sync(now_unix=1_000_000.0)
    assert pfg._last_sync_unix == 0.0


def test_pnl_flow_gate_runs_on_interval_with_mocked_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pfg.reset_pnl_flow_gate_state_for_tests()
    monkeypatch.setenv("PNL_FLOW_AUTO_SYNC_ENABLED", "true")
    monkeypatch.setenv("PNL_FLOW_ONCHAIN_ENABLED", "true")
    monkeypatch.setenv("PNL_FLOW_WALLET", WALLET)
    monkeypatch.setenv("PNL_FLOW_AUTO_SYNC_INTERVAL_HOURS", "6")
    deposit_tx = "0x" + "e" * 64
    withdraw_tx = "0x" + "f" * 64
    get_logs, block_ts = _mock_rpc_get_logs(deposit_tx, withdraw_tx)
    jsonl_path = tmp_path / "pnl_flow_events.jsonl"

    pfg.maybe_run_pnl_flow_sync(
        now_unix=1_000_000.0,
        jsonl_path=jsonl_path,
        get_logs=get_logs,
        get_block_timestamp=block_ts,
        latest_block_number=1000,
        token_addresses=[("USDT", USDT)],
        now_utc=datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc),
    )
    out = capsys.readouterr().out
    assert "[nanoclaw] PNL_FLOW_SYNC | scraped=2 appended=2 wallet=0x05eF…FBe6" in out
    assert pfg._last_sync_unix == pytest.approx(1_000_000.0)

    capsys.readouterr()
    pfg.maybe_run_pnl_flow_sync(
        now_unix=1_000_100.0,
        jsonl_path=jsonl_path,
        get_logs=get_logs,
        get_block_timestamp=block_ts,
        latest_block_number=1000,
        token_addresses=[("USDT", USDT)],
        now_utc=datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert capsys.readouterr().out == ""
