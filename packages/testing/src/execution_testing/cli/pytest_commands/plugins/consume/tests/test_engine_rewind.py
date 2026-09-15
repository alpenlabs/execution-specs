"""Tests for the EngineX canonical-head rewind barrier."""

from unittest.mock import Mock, call, patch

import pytest

from execution_testing.base_types import Hash

from ..simulators.helpers.exceptions import LoggedError
from ..simulators.simulator_logic.test_via_engine import (
    wait_for_canonical_head,
)

GENESIS_HASH = Hash(0)
OTHER_HASH = Hash(1)


def test_wait_for_canonical_head_returns_when_genesis_is_latest() -> None:
    """Do not sleep when the canonical rewind already completed."""
    eth_rpc = Mock()
    eth_rpc.get_block_by_number.return_value = {"hash": str(GENESIS_HASH)}

    with patch("time.sleep") as sleep:
        wait_for_canonical_head(eth_rpc, GENESIS_HASH)

    eth_rpc.get_block_by_number.assert_called_once_with(
        "latest", full_txs=False
    )
    sleep.assert_not_called()


def test_wait_for_canonical_head_polls_until_rewind_completes() -> None:
    """Do not execute the next fixture while the previous head is visible."""
    eth_rpc = Mock()
    eth_rpc.get_block_by_number.side_effect = [
        {"hash": str(OTHER_HASH)},
        {"hash": str(GENESIS_HASH)},
    ]

    with patch("time.sleep") as sleep:
        wait_for_canonical_head(
            eth_rpc,
            GENESIS_HASH,
            timeout=1.0,
            poll_interval=0.01,
        )

    assert eth_rpc.get_block_by_number.call_args_list == [
        call("latest", full_txs=False),
        call("latest", full_txs=False),
    ]
    sleep.assert_called_once()


def test_wait_for_canonical_head_times_out_with_observed_head() -> None:
    """Report both hashes when the client never completes its rewind."""
    eth_rpc = Mock()
    eth_rpc.get_block_by_number.return_value = {"hash": str(OTHER_HASH)}

    with (
        patch("time.monotonic", side_effect=[10.0, 11.0]),
        pytest.raises(LoggedError, match="Timed out.*observed") as error,
    ):
        wait_for_canonical_head(
            eth_rpc,
            GENESIS_HASH,
            timeout=0.5,
            poll_interval=0.01,
        )

    assert str(GENESIS_HASH) in str(error.value)
    assert str(OTHER_HASH) in str(error.value)


def test_wait_for_canonical_head_rejects_malformed_response() -> None:
    """Fail explicitly when the client omits its canonical head hash."""
    eth_rpc = Mock()
    eth_rpc.get_block_by_number.return_value = {"number": "0x0"}

    with pytest.raises(LoggedError, match="missing string field 'hash'"):
        wait_for_canonical_head(eth_rpc, GENESIS_HASH)


def test_wait_for_canonical_head_propagates_rpc_failure() -> None:
    """Preserve the RPC failure as the cause of the barrier error."""
    eth_rpc = Mock()
    rpc_error = RuntimeError("RPC unavailable")
    eth_rpc.get_block_by_number.side_effect = rpc_error

    with pytest.raises(LoggedError, match="Failed to query") as error:
        wait_for_canonical_head(eth_rpc, GENESIS_HASH)

    assert error.value.__cause__ is rpc_error
