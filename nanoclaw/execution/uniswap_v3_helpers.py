"""Reusable Uniswap V3 fallback helpers."""

from __future__ import annotations

from collections.abc import Callable

from web3 import Web3


def resolve_spendable_usdc_token(
    w3,
    *,
    wallet: str,
    primary_usdc: str,
    secondary_usdc: str,
    amount_in: int,
    addr_probe: Callable[[str], str],
    log_prefix: str = "",
) -> str:
    """Pick USDC token contract with enough spendable balance for this swap."""
    token_candidates = [Web3.to_checksum_address(primary_usdc)]
    alt = str(secondary_usdc or "").strip()
    if alt:
        alt_cs = Web3.to_checksum_address(alt)
        if alt_cs.lower() != token_candidates[0].lower():
            token_candidates.append(alt_cs)

    erc20_balance_abi = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function",
        }
    ]

    best_token = token_candidates[0]
    best_balance = -1
    for token_addr in token_candidates:
        try:
            bal_raw = int(
                w3.eth.contract(address=token_addr, abi=erc20_balance_abi)
                .functions.balanceOf(wallet)
                .call()
            )
        except Exception:
            bal_raw = 0
        if bal_raw >= int(amount_in):
            if token_addr.lower() != Web3.to_checksum_address(primary_usdc).lower():
                print(f"{log_prefix}USDC source auto-selected for spendability: {addr_probe(token_addr)}")
            return token_addr
        if bal_raw > best_balance:
            best_balance = bal_raw
            best_token = token_addr

    print(
        f"{log_prefix}USDC source best-effort selected: {addr_probe(best_token)} "
        f"(have={best_balance}, need={int(amount_in)})"
    )
    return best_token


def ensure_erc20_allowance(
    w3,
    *,
    token_address: str,
    owner: str,
    spender: str,
    required_amount: int,
    signer_key: str,
    chain_id: int = 137,
    log_prefix: str = "",
) -> None:
    """Ensure ERC20 spender allowance >= required amount, approving max if needed."""
    token_cs = Web3.to_checksum_address(token_address)
    spender_cs = Web3.to_checksum_address(spender)
    abi = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
            "name": "allowance",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function",
        },
    ]
    token_contract = w3.eth.contract(address=token_cs, abi=abi)
    current_allowance = int(token_contract.functions.allowance(owner, spender_cs).call())
    if current_allowance >= int(required_amount):
        print(
            f"{log_prefix}Allowance check | spender={spender_cs} | current={current_allowance} | "
            f"needed={int(required_amount)} | action=none"
        )
        return

    approve_tx = token_contract.functions.approve(
        spender_cs,
        2**256 - 1,
    ).build_transaction(
        {
            "from": owner,
            "nonce": w3.eth.get_transaction_count(owner),
            "gas": 140000,
            "gasPrice": w3.eth.gas_price * 15 // 10,
            "chainId": int(chain_id),
        }
    )
    signed_approve = w3.eth.account.sign_transaction(approve_tx, signer_key)
    approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=300)
    if int(receipt.get("status", 0)) == 0:
        raise RuntimeError(f"{log_prefix}ERC20 max approval failed for spender {spender_cs}")

    print(
        f"{log_prefix}Allowance check | spender={spender_cs} | current={current_allowance} | "
        f"needed={int(required_amount)} | action=approved/max"
    )


def quote_exact_input_single(
    w3,
    *,
    quoter_address: str,
    quoter_abi: list[dict],
    token_in: str,
    token_out: str,
    amount_in: int,
    slippage_bps: int,
    fee: int = 3000,
) -> tuple[int, int]:
    """Quote amountOut via V3 quoter and derive amountOutMinimum from slippage bps."""
    quoter = w3.eth.contract(address=Web3.to_checksum_address(quoter_address), abi=quoter_abi)
    amount_out = int(
        quoter.functions.quoteExactInputSingle(
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            int(fee),
            int(amount_in),
            0,
        ).call()
    )
    amount_out_min = max(1, (amount_out * (10000 - min(int(slippage_bps), 9999))) // 10000)
    return amount_out, amount_out_min
