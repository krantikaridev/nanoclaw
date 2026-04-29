"""Router path shaping (offline: no RPC)."""

from web3 import Web3

from constants import USDC, WMATIC
from swap_executor import build_polygon_swap_path_candidates


def test_candidates_include_direct_between_usdc_and_wmatic():
    a = Web3.to_checksum_address(USDC)
    b = Web3.to_checksum_address(WMATIC)
    paths = build_polygon_swap_path_candidates(a, b)
    assert [a, b] in paths or paths[0] == [a, b]


def test_candidates_list_unique_paths():
    a = Web3.to_checksum_address(USDC)
    b = Web3.to_checksum_address(WMATIC)
    paths = build_polygon_swap_path_candidates(a, b)
    seen = {"::".join(p) for p in paths}
    assert len(seen) == len(paths)


def test_candidates_length_for_non_stable_pair_has_direct_and_maybe_hops():
    wbtc = Web3.to_checksum_address("0x1BFD67037B42Cf73acf204706795bF64736C834e")
    weth = Web3.to_checksum_address("0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619")
    paths = build_polygon_swap_path_candidates(wbtc, weth)
    assert len(paths) >= 1
    assert all(len(p) >= 2 for p in paths)
