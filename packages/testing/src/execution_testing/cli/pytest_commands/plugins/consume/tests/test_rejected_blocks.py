"""Tests for the block rejection tracker used by the engine simulators."""

import pytest

from execution_testing.base_types import Hash
from execution_testing.exceptions import (
    BlockException,
    TransactionException,
    UndefinedException,
)
from execution_testing.rpc.rpc_types import (
    BlockTransactionExceptionWithMessage,
)

from ..simulators.helpers.exceptions import (
    EXCEPTION_MAPPERS,
    LoggedError,
    RethExceptionMapper,
)
from ..simulators.helpers.rejected_blocks import (
    BlockRejectionTracker,
    matches_expected_exception,
    verify_block_rejection,
)

CLIENT_A = "client-a"
CLIENT_B = "client-b"
BLOCK_1 = Hash(1)
BLOCK_2 = Hash(2)

EXCESS_BLOB_GAS_ERROR = BlockTransactionExceptionWithMessage(
    exceptions=[BlockException.INCORRECT_EXCESS_BLOB_GAS],
    message="invalid excess blob gas: got 1179648, expected 1048576",
)
CACHED_REJECTION_ERROR = UndefinedException(
    "links to previously rejected block",
    mapper_name="RethExceptionMapper",
)


def test_alpen_uses_reth_exception_mapper() -> None:
    """Alpen's Reth-derived validation strings use the Reth mapper."""
    assert isinstance(EXCEPTION_MAPPERS["alpen"], RethExceptionMapper)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Failed to recover the block",
            {TransactionException.INVALID_SIGNATURE_VRS},
        ),
        (
            "Failed to recover the signer",
            {TransactionException.INVALID_SIGNATURE_VRS},
        ),
        (
            "Unexpected type flag",
            {
                TransactionException.INVALID_SIGNATURE_VRS,
                TransactionException.GASLIMIT_PRICE_PRODUCT_OVERFLOW,
            },
        ),
    ],
)
def test_reth_maps_raw_transaction_decode_failures(
    message: str,
    expected: set[TransactionException],
) -> None:
    """Map Reth's lossy raw-transaction decode errors to valid candidates."""
    mapped = RethExceptionMapper().message_to_exception(message)
    assert not isinstance(mapped, UndefinedException)
    assert set(mapped) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "nonce overflow in transaction",
            TransactionException.NONCE_IS_MAX,
        ),
        (
            "overflow payment in transaction",
            TransactionException.GASLIMIT_PRICE_PRODUCT_OVERFLOW,
        ),
    ],
)
def test_reth_maps_distinct_transaction_overflows(
    message: str,
    expected: TransactionException,
) -> None:
    """Do not collapse nonce and gas-payment overflows into one class."""
    mapped = RethExceptionMapper().message_to_exception(message)
    assert not isinstance(mapped, UndefinedException)
    assert mapped == [expected]


def test_first_rejection_returns_the_error_itself() -> None:
    """The first rejection of a block records and returns its own error."""
    tracker = BlockRejectionTracker()
    assert (
        tracker.track(CLIENT_A, BLOCK_1, EXCESS_BLOB_GAS_ERROR)
        is EXCESS_BLOB_GAS_ERROR
    )


def test_resubmission_returns_first_error() -> None:
    """Rejections after the first return the first recorded error."""
    tracker = BlockRejectionTracker()
    tracker.track(CLIENT_A, BLOCK_1, EXCESS_BLOB_GAS_ERROR)
    assert (
        tracker.track(CLIENT_A, BLOCK_1, CACHED_REJECTION_ERROR)
        is EXCESS_BLOB_GAS_ERROR
    )
    # The first error is not overwritten by later rejections.
    assert (
        tracker.track(CLIENT_A, BLOCK_1, CACHED_REJECTION_ERROR)
        is EXCESS_BLOB_GAS_ERROR
    )


def test_rejections_are_tracked_per_client() -> None:
    """A rejection by one client is not the first error for another."""
    tracker = BlockRejectionTracker()
    tracker.track(CLIENT_A, BLOCK_1, EXCESS_BLOB_GAS_ERROR)
    assert (
        tracker.track(CLIENT_B, BLOCK_1, CACHED_REJECTION_ERROR)
        is CACHED_REJECTION_ERROR
    )


def test_rejections_are_tracked_per_block() -> None:
    """A rejection of one block is not the first error for another."""
    tracker = BlockRejectionTracker()
    tracker.track(CLIENT_A, BLOCK_1, EXCESS_BLOB_GAS_ERROR)
    assert (
        tracker.track(CLIENT_A, BLOCK_2, CACHED_REJECTION_ERROR)
        is CACHED_REJECTION_ERROR
    )


def test_matching_first_rejection() -> None:
    """A tracked rejection matches its mapped exception."""
    assert matches_expected_exception(
        EXCESS_BLOB_GAS_ERROR, BlockException.INCORRECT_EXCESS_BLOB_GAS
    )


def test_matching_first_rejection_with_exception_list() -> None:
    """A tracked rejection matches a list containing its exception."""
    assert matches_expected_exception(
        EXCESS_BLOB_GAS_ERROR,
        [
            BlockException.INCORRECT_BLOB_GAS_USED,
            BlockException.INCORRECT_EXCESS_BLOB_GAS,
        ],
    )


def test_mismatching_first_rejection() -> None:
    """A tracked rejection does not match a different exception."""
    assert not matches_expected_exception(
        EXCESS_BLOB_GAS_ERROR, BlockException.INCORRECT_BLOB_GAS_USED
    )


def test_undefined_first_rejection_never_matches() -> None:
    """An unmappable tracked rejection cannot be verified as a match."""
    assert not matches_expected_exception(
        CACHED_REJECTION_ERROR,
        BlockException.INCORRECT_EXCESS_BLOB_GAS,
    )


def test_no_expected_exception_never_matches() -> None:
    """Without an expected exception there is nothing to match."""
    assert not matches_expected_exception(EXCESS_BLOB_GAS_ERROR, None)


def test_verify_matching_error_passes() -> None:
    """A rejection with the expected exception verifies silently."""
    verify_block_rejection(
        BlockException.INCORRECT_EXCESS_BLOB_GAS,
        EXCESS_BLOB_GAS_ERROR,
        EXCESS_BLOB_GAS_ERROR,
        BLOCK_1,
        strict_exception_matching=True,
    )


def test_verify_first_rejection_mismatch_raises() -> None:
    """A block's first rejection is verified strictly."""
    with pytest.raises(LoggedError, match="Undefined exception message"):
        verify_block_rejection(
            BlockException.INCORRECT_EXCESS_BLOB_GAS,
            CACHED_REJECTION_ERROR,
            CACHED_REJECTION_ERROR,
            BLOCK_1,
            strict_exception_matching=True,
        )


def test_verify_unexpected_error_raises() -> None:
    """A mapped but unexpected error fails strict verification."""
    with pytest.raises(LoggedError, match="unexpected validation error"):
        verify_block_rejection(
            BlockException.INCORRECT_BLOB_GAS_USED,
            EXCESS_BLOB_GAS_ERROR,
            EXCESS_BLOB_GAS_ERROR,
            BLOCK_1,
            strict_exception_matching=True,
        )


def test_verify_accepts_cached_resubmission_rejection() -> None:
    """A cache error is accepted if the first rejection matched."""
    verify_block_rejection(
        BlockException.INCORRECT_EXCESS_BLOB_GAS,
        CACHED_REJECTION_ERROR,
        EXCESS_BLOB_GAS_ERROR,
        BLOCK_1,
        strict_exception_matching=True,
    )


def test_verify_mismatch_only_warns_without_strict_matching() -> None:
    """A mismatched rejection does not fail without strict matching."""
    verify_block_rejection(
        BlockException.INCORRECT_EXCESS_BLOB_GAS,
        CACHED_REJECTION_ERROR,
        CACHED_REJECTION_ERROR,
        BLOCK_1,
        strict_exception_matching=False,
    )
