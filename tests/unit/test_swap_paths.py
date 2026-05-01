"""Router path shaping (offline: no RPC)."""

from web3 import Web3

from constants import USDC, USDT, WMATIC
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


def test_candidates_use_only_direct_path_when_output_is_wmatic():
    a = Web3.to_checksum_address(USDT)
    b = Web3.to_checksum_address(WMATIC)
    paths = build_polygon_swap_path_candidates(a, b)
    assert paths == [[a, b]]


def test_candidates_skip_redundant_usdc_hop_when_input_is_usdc():
    a = Web3.to_checksum_address(USDC)
    b = Web3.to_checksum_address("0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619")
    wm = Web3.to_checksum_address(WMATIC)
    paths = build_polygon_swap_path_candidates(a, b)
    assert paths == [[a, b], [a, wm, b]]


def test_candidates_for_non_stable_pair_include_direct_wmatic_and_usdc_hops_in_order():
    wbtc = Web3.to_checksum_address("0x1BFD67037B42Cf73acf204706795bF64736C834e")
    weth = Web3.to_checksum_address("0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619")
    wm = Web3.to_checksum_address(WMATIC)
    uc = Web3.to_checksum_address(USDC)

    paths = build_polygon_swap_path_candidates(wbtc, weth)
    assert paths == [
        [wbtc, weth],
        [wbtc, wm, weth],
        [wbtc, uc, weth],
    ]
