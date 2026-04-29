"""Router ABI combined list must stay flat (list of dict ABI items), never [[...]]."""

import pytest

import constants


def test_router_quote_fragment_is_flat_entries():
    fragment = constants._ROUTER_AMOUNT_OUT_ENTRIES
    assert fragment
    assert all(isinstance(entry, dict) for entry in fragment)
    assert all("type" in entry for entry in fragment)


def test_combined_router_abi_is_flat_concatenation():
    combined = constants.ROUTER_SWAP_AND_QUOTE_ABI
    assert isinstance(combined, list)
    assert all(isinstance(entry, dict) for entry in combined)
    assert len(combined) == len(constants.ROUTER_ABI) + len(constants._ROUTER_AMOUNT_OUT_ENTRIES)


@pytest.mark.parametrize(
    "fragment, expected_len",
    [
        ({ "name": "f", "type": "function" }, 1),
        ([{"name": "a", "type": "function"}, {"name": "b", "type": "function"}], 2),
        ([], 0),
    ],
)
def test_abi_fragment_to_entry_list_normalizes(fragment, expected_len):
    assert len(constants._abi_fragment_to_entry_list(fragment)) == expected_len
