"""Test the pre-allocation models used during test execution."""

from itertools import count
from typing import Any
from unittest.mock import Mock

import pytest

from execution_testing.base_types import Address, Hash
from execution_testing.forks import Prague
from execution_testing.test_types import EOA
from execution_testing.vm import Op

from ...shared.address_stubs import StubAddress, StubEOA
from ...shared.pre_alloc import AllocFlags
from ..pre_alloc import AddressStubs, Alloc

ADDR_1 = Address("0x0000000000000000000000000000000000000001")
DEPOSIT_ADDR = Address("0x00000000219ab540356cbb839cbe05303d7705fa")
TEST_PKEY = Hash(
    0x45A915E4D060149EB4365960E6A7A45F334393093061116B197E3240065FF2D8
)
TEST_ADDR = Address("0xa94f5374fce5edbc8e2a8697c15331677e6ebf0b")


@pytest.mark.parametrize("required_balance", [None, 0, 12345])
def test_deferred_funding_for_unused_eoa(required_balance: int | None) -> None:
    """Unused EOAs cost zero value; used EOAs retain their required balance."""
    alloc = Alloc(
        sender=EOA(key=TEST_PKEY),
        eth_rpc=Mock(),
        eoa_iterator=(EOA(key=key) for key in count(1)),
        chain_id=1,
        fork=Prague,
        flags=AllocFlags.NONE,
    )
    eoa = alloc.fund_eoa()
    balances: dict[Address, int] = (
        {} if required_balance is None else {eoa: required_balance}
    )
    pending_tx = alloc._pending_txs[0]
    original_nonce = pending_tx.nonce
    assert pending_tx.value is None
    alloc.minimum_balance_for_pending_transactions(
        balances,
        gas_price=10,
        max_fee_per_gas=10,
        max_priority_fee_per_gas=0,
        max_fee_per_blob_gas=1,
    )
    assert pending_tx.value == (required_balance or 0)
    assert pending_tx.nonce == original_nonce
    assert balances == (
        {} if required_balance is None else {eoa: required_balance}
    )


def test_unresolved_non_funding_value_still_fails() -> None:
    """Do not silently coerce malformed setup operations to zero transfers."""
    alloc = Alloc(
        sender=EOA(key=TEST_PKEY),
        eth_rpc=Mock(),
        eoa_iterator=(EOA(key=key) for key in count(1)),
        chain_id=1,
        fork=Prague,
        flags=AllocFlags.NONE,
    )
    alloc._add_pending_tx(
        action="deploy_contract",
        target=None,
        to=ADDR_1,
        value=None,
        gas_limit=21000,
    )
    with pytest.raises(ValueError, match="Sender balance must be set"):
        alloc.minimum_balance_for_pending_transactions(
            {},
            gas_price=10,
            max_fee_per_gas=10,
            max_priority_fee_per_gas=0,
            max_fee_per_blob_gas=1,
        )


def test_deploy_contract_accepts_raw_bytecode() -> None:
    """Treat raw bytes as runtime code instead of requiring opcode metadata."""
    alloc = Alloc(
        sender=EOA(key=TEST_PKEY),
        eth_rpc=Mock(),
        eoa_iterator=(EOA(key=key) for key in count(1)),
        chain_id=1,
        fork=Prague,
        flags=AllocFlags.NONE,
    )

    contract = alloc.deploy_contract(bytes(Op.STOP))

    assert len(alloc._pending_txs) == 1
    assert alloc._pending_txs[0].to is None
    assert alloc._deployed_contracts == [(contract, Op.STOP)]


@pytest.mark.parametrize(
    "minimum_balance,current_balance,requested_amount,expected_transfer",
    [
        pytest.param(False, 7, 11, 11, id="additive_balance"),
        pytest.param(True, 7, 11, 4, id="minimum_balance"),
    ],
)
def test_fund_address_does_not_execute_recipient(
    minimum_balance: bool,
    current_balance: int,
    requested_amount: int,
    expected_transfer: int,
) -> None:
    """Fund arbitrary addresses through a transient SELFDESTRUCT helper."""
    eth_rpc = Mock()
    eth_rpc.get_balances.return_value = [current_balance]
    alloc = Alloc(
        sender=EOA(key=TEST_PKEY),
        eth_rpc=eth_rpc,
        eoa_iterator=(EOA(key=key) for key in count(1)),
        chain_id=1,
        fork=Prague,
        flags=AllocFlags.NONE,
    )

    alloc.fund_address(
        ADDR_1,
        requested_amount,
        minimum_balance=minimum_balance,
    )
    alloc.resolve_deferred_checks()

    eth_rpc.get_balances.assert_called_once_with([ADDR_1])
    pending_tx = alloc._pending_txs[0]
    assert pending_tx.to is None
    assert pending_tx.data == Op.SELFDESTRUCT(ADDR_1)
    assert pending_tx.value == expected_transfer
    account = alloc[ADDR_1]
    assert account is not None
    assert account.balance == current_balance + expected_transfer


def test_fund_address_skips_satisfied_minimum() -> None:
    """Do not queue a transfer when the existing balance is sufficient."""
    eth_rpc = Mock()
    eth_rpc.get_balances.return_value = [11]
    alloc = Alloc(
        sender=EOA(key=TEST_PKEY),
        eth_rpc=eth_rpc,
        eoa_iterator=(EOA(key=key) for key in count(1)),
        chain_id=1,
        fork=Prague,
        flags=AllocFlags.NONE,
    )

    alloc.fund_address(ADDR_1, 11, minimum_balance=True)
    alloc.resolve_deferred_checks()

    assert alloc._pending_txs == []
    account = alloc[ADDR_1]
    assert account is not None
    assert account.balance == 11


@pytest.mark.parametrize(
    "input_value,expected",
    [
        pytest.param(
            "{}",
            AddressStubs({}),
            id="empty_address_stubs_string",
        ),
        pytest.param(
            '{"some_address": {"addr": "0x0000000000000000000000000000000000000001"}}',  # noqa: E501
            AddressStubs({"some_address": StubAddress(addr=ADDR_1)}),
            id="address_stubs_string_with_some_address",
        ),
    ],
)
def test_address_stubs(input_value: Any, expected: AddressStubs) -> None:
    """Test the address stubs."""
    assert AddressStubs.model_validate_json_or_file(input_value) == expected


@pytest.mark.parametrize(
    "file_name,file_contents,expected",
    [
        pytest.param(
            "empty.json",
            "{}",
            AddressStubs({}),
            id="empty_address_stubs_json",
        ),
        pytest.param(
            "one_address.json",
            '{"DEPOSIT_CONTRACT_ADDRESS": {"addr": "0x00000000219ab540356cbb839cbe05303d7705fa"}}',  # noqa: E501
            AddressStubs(
                {
                    "DEPOSIT_CONTRACT_ADDRESS": StubAddress(
                        addr=DEPOSIT_ADDR,
                    ),
                }
            ),
            id="single_address_json",
        ),
    ],
)
def test_address_stubs_from_files(
    pytester: pytest.Pytester,
    file_name: str,
    file_contents: str,
    expected: AddressStubs,
) -> None:
    """Test the address stubs."""
    filename = pytester.path.joinpath(file_name)
    filename.write_text(file_contents)

    assert AddressStubs.model_validate_json_or_file(str(filename)) == expected


def test_address_stubs_file_not_found(pytester: pytest.Pytester) -> None:
    """Test that a missing JSON file raises FileNotFoundError."""
    missing_test = pytester.path.joinpath("nonexistent.json")
    with pytest.raises(FileNotFoundError):
        AddressStubs.model_validate_json_or_file(str(missing_test))


def test_address_stubs_getitem_returns_address() -> None:
    """Verify __getitem__ returns the Address, not the stub entry."""
    stubs = AddressStubs({"label": StubAddress(addr=ADDR_1)})
    assert stubs["label"] == ADDR_1
    assert isinstance(stubs["label"], Address)


def test_address_stubs_contains() -> None:
    """Verify __contains__ checks for label presence."""
    stubs = AddressStubs({"label": StubAddress(addr=ADDR_1)})
    assert "label" in stubs
    assert "other" not in stubs


def test_address_stubs_with_pkey() -> None:
    """Parse a JSON string with a private key entry."""
    json_str = (
        '{"eoa": {"addr": "' + str(TEST_ADDR) + '", '
        '"pkey": "' + str(TEST_PKEY) + '"}}'
    )
    stubs = AddressStubs.model_validate_json_or_file(json_str)
    assert stubs["eoa"] == TEST_ADDR
    assert stubs.is_eoa("eoa")
    entry = stubs.get_entry("eoa")
    assert isinstance(entry, StubEOA)
    assert entry.pkey == TEST_PKEY


def test_address_stubs_is_eoa() -> None:
    """Verify is_eoa distinguishes entries."""
    stubs = AddressStubs(
        {
            "contract": StubAddress(addr=ADDR_1),
            "eoa": StubEOA(addr=TEST_ADDR, pkey=TEST_PKEY),
        }
    )
    assert not stubs.is_eoa("contract")
    assert stubs.is_eoa("eoa")
    assert not stubs.is_eoa("nonexistent")
