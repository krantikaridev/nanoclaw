from modules import wallet_performance as wp
import config as cfg


def test_wallet_performance_records_and_closes_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_FILE", str(tmp_path / "wallet_perf.json"))
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_WINDOW_TRADES", 25)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_MIN_TRADES", 2)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_POOR_WINRATE", 0.4)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_POOR_AVG_PNL_USD", -0.2)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_PENALTY_MULTIPLIER", 0.65)

    wp.record_copy_entry("0xabc", entry_price_usd=1.0, notional_usd=20.0)
    closed = wp.record_copy_exit(exit_price_usd=1.1, exit_notional_usd=20.0)

    assert len(closed) == 1
    assert closed[0]["wallet"] == "0xabc"
    assert float(closed[0]["pnl_usd"]) > 0.0
    health = wp.wallet_health("0xabc")
    assert float(health["trades"]) == 1.0
    assert float(health["win_rate"]) == 1.0


def test_wallet_performance_deprioritizes_poor_wallet(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_FILE", str(tmp_path / "wallet_perf.json"))
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_WINDOW_TRADES", 5)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_MIN_TRADES", 3)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_POOR_WINRATE", 0.5)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_POOR_AVG_PNL_USD", -0.1)
    monkeypatch.setattr(cfg, "COPY_WALLET_PERFORMANCE_PENALTY_MULTIPLIER", 0.6)

    for _ in range(3):
        wp.record_copy_entry("0xpoor", entry_price_usd=1.0, notional_usd=10.0)
        wp.record_copy_exit(exit_price_usd=0.9, exit_notional_usd=10.0)

    health = wp.wallet_health("0xpoor")
    assert bool(health["deprioritize"]) is True
    assert float(health["allocation_multiplier"]) == 0.6
