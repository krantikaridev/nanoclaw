import math
import unittest
from unittest.mock import patch

from nanoclaw.utils.gas_protector import GasProtector


class FakeEth:
    def __init__(self, gas_price_wei, balance_wei):
        self.gas_price = gas_price_wei
        self._balance_wei = balance_wei

    def get_balance(self, _address):
        return self._balance_wei


class FakeWeb3:
    def __init__(self, gas_price_wei, balance_wei):
        self.eth = FakeEth(gas_price_wei=gas_price_wei, balance_wei=balance_wei)

    def from_wei(self, value, unit):
        if unit == "gwei":
            return value / 10**9
        if unit == "ether":
            return value / 10**18
        raise ValueError(f"Unsupported unit: {unit}")


class GasProtectorTests(unittest.TestCase):
    def test_builder_supports_chaining_and_config_capture(self):
        protector = (
            GasProtector.builder()
            .with_max_gwei(80)
            .with_urgent_gwei(120)
            .with_min_pol_balance(0.25)
            .with_primary_rpc("https://primary")
            .with_fallback_rpcs(["https://fallback-a", "https://fallback-b"])
            .with_retry_attempts(3)
            .build()
        )

        self.assertEqual(protector.config.max_gwei, 80.0)
        self.assertEqual(protector.config.urgent_gwei, 120.0)
        self.assertEqual(protector.config.min_pol_balance, 0.25)
        self.assertEqual(protector.config.primary_rpc, "https://primary")
        self.assertEqual(protector.config.fallback_rpcs, ("https://fallback-a", "https://fallback-b"))
        self.assertEqual(protector.config.retry_attempts, 3)

    def test_uses_fallback_rpc_when_primary_fails(self):
        protector = (
            GasProtector.builder()
            .with_primary_rpc("https://primary")
            .with_fallback_rpcs(["https://fallback"])
            .with_retry_attempts(1)
            .build()
        )

        def fake_build_web3(rpc_url):
            if rpc_url == "https://primary":
                raise RuntimeError("primary unavailable")
            return FakeWeb3(gas_price_wei=55 * 10**9, balance_wei=3 * 10**18)

        with patch.object(protector, "_build_web3", side_effect=fake_build_web3):
            status = protector.get_safe_status(address="0xabc", min_pol=0.5)

        self.assertTrue(status["ok"])
        self.assertEqual(status["gas_rpc"], "https://fallback")
        self.assertEqual(status["pol_rpc"], "https://fallback")
        self.assertEqual(status["gas_gwei"], 55.0)
        self.assertEqual(status["pol_balance"], 3.0)

    def test_returns_safe_values_when_all_rpcs_fail(self):
        protector = (
            GasProtector.builder()
            .with_max_gwei(80)
            .with_urgent_gwei(120)
            .with_primary_rpc("https://primary")
            .with_fallback_rpcs(["https://fallback"])
            .with_retry_attempts(1)
            .build()
        )

        with patch.object(protector, "_build_web3", side_effect=RuntimeError("all RPCs failed")):
            self.assertFalse(protector.is_gas_acceptable())
            self.assertFalse(protector.has_enough_pol("0xabc"))
            status = protector.get_safe_status(address="0xabc")

        self.assertFalse(status["ok"])
        self.assertFalse(status["gas_ok"])
        self.assertFalse(status["pol_ok"])
        self.assertIsNone(status["gas_rpc"])
        self.assertIsNone(status["pol_rpc"])
        self.assertTrue(math.isclose(status["gas_gwei"], 81.0))
        self.assertTrue(math.isclose(status["pol_balance"], 0.0))

    def test_urgent_threshold_is_applied(self):
        protector = (
            GasProtector.builder()
            .with_max_gwei(80)
            .with_urgent_gwei(120)
            .with_primary_rpc("https://primary")
            .with_retry_attempts(1)
            .build()
        )

        with patch.object(
            protector,
            "_build_web3",
            return_value=FakeWeb3(gas_price_wei=100 * 10**9, balance_wei=1 * 10**18),
        ):
            self.assertFalse(protector.is_gas_acceptable())
            self.assertTrue(protector.is_gas_acceptable(urgent=True))

    def test_pol_balance_check_never_raises(self):
        protector = (
            GasProtector.builder()
            .with_primary_rpc("https://primary")
            .with_retry_attempts(1)
            .build()
        )

        with patch.object(
            protector,
            "_build_web3",
            return_value=FakeWeb3(gas_price_wei=20 * 10**9, balance_wei=int(0.2 * 10**18)),
        ):
            self.assertEqual(protector.get_pol_balance("0xabc"), 0.2)
            self.assertTrue(protector.has_enough_pol("0xabc", min_pol=0.1))
            self.assertFalse(protector.has_enough_pol("0xabc", min_pol=0.3))

    def test_missing_web3_dependency_still_returns_safe_values(self):
        protector = (
            GasProtector.builder()
            .with_max_gwei(80)
            .with_urgent_gwei(120)
            .with_primary_rpc("https://primary")
            .with_retry_attempts(1)
            .build()
        )

        status = protector.get_safe_status("0xabc")

        self.assertEqual(protector.get_gas_price_gwei(), 81.0)
        self.assertEqual(protector.get_pol_balance("0xabc"), 0.0)
        self.assertFalse(protector.is_gas_acceptable())
        self.assertFalse(protector.has_enough_pol("0xabc"))
        self.assertFalse(status["ok"])
        self.assertIsNone(status["gas_rpc"])
        self.assertIsNone(status["pol_rpc"])


if __name__ == "__main__":
    unittest.main()
