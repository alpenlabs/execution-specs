"""
A hive based simulator that executes blocks against clients using the
`engine_newPayloadVX` method from the Engine API.

The unified test function in this module supports both:
- `BlockchainEngineFixtures`, the original engine mode with a
  1-to-1 relationship between client instance and test, i.e.,
  each test is executed against a fresh client instance.
- `BlockchainEngineXFixtures`, enginex mode with client reuse
  across tests with shared pre-alloc groups.

Each `engine_newPayloadVX` is verified against the appropriate VALID/INVALID
responses.
"""

import time
from typing import Union

from hive.client import Client

from execution_testing.base_types import Hash
from execution_testing.fixtures import (
    BlockchainEngineFixture,
    BlockchainEngineXFixture,
)
from execution_testing.fixtures.blockchain import FixtureHeader
from execution_testing.logging import get_logger
from execution_testing.rpc import (
    EngineRPC,
    EthRPC,
    ForkchoiceUpdateTimeoutError,
)
from execution_testing.rpc.rpc_types import (
    ForkchoiceState,
    JSONRPCError,
    PayloadStatusEnum,
)

from ..helpers.exceptions import (
    GenesisBlockMismatchExceptionError,
    LoggedError,
)
from ..helpers.rejected_blocks import (
    BlockRejectionTracker,
    verify_block_rejection,
)
from ..helpers.timing import TimingData

logger = get_logger(__name__)

CANONICAL_HEAD_TIMEOUT_SECONDS = 60.0
CANONICAL_HEAD_POLL_INTERVAL_SECONDS = 0.05


def wait_for_canonical_head(
    eth_rpc: EthRPC,
    expected_head_hash: Hash,
    *,
    timeout: float = CANONICAL_HEAD_TIMEOUT_SECONDS,
    poll_interval: float = CANONICAL_HEAD_POLL_INTERVAL_SECONDS,
) -> None:
    """
    Wait until ``eth_getBlockByNumber(latest)`` exposes ``expected_head_hash``.

    Some clients acknowledge ``engine_forkchoiceUpdated`` before their
    canonical database unwind is complete. EngineX reuses a client for sibling
    fixtures and rewinds it to genesis between tests, so sending the next
    payload immediately can execute it against state from the previous branch.
    Treat the canonical RPC head as the completion barrier before continuing.
    """
    if timeout <= 0:
        raise ValueError("canonical head timeout must be greater than zero")
    if poll_interval <= 0:
        raise ValueError(
            "canonical head poll interval must be greater than zero"
        )

    expected_hash = str(expected_head_hash).lower()
    started_at = time.monotonic()
    attempts = 0

    while True:
        attempts += 1
        try:
            latest_block = eth_rpc.get_block_by_number(
                "latest", full_txs=False
            )
        except Exception as error:
            raise LoggedError(
                "Failed to query the canonical head while waiting for "
                f"EngineX rewind to {expected_hash}: {error}"
            ) from error

        if not isinstance(latest_block, dict):
            response_type = type(latest_block).__name__
            raise LoggedError(
                "Malformed eth_getBlockByNumber(latest) response while "
                "waiting for EngineX rewind: expected an object, got "
                f"{response_type}"
            )

        observed_hash = latest_block.get("hash")
        if not isinstance(observed_hash, str):
            raise LoggedError(
                "Malformed eth_getBlockByNumber(latest) response while "
                "waiting for EngineX rewind: missing string field 'hash'"
            )

        if observed_hash.lower() == expected_hash:
            if attempts > 1:
                elapsed = time.monotonic() - started_at
                logger.info(
                    "Canonical head reached %s after %d polls (%.3fs)",
                    expected_hash,
                    attempts,
                    elapsed,
                )
            return

        elapsed = time.monotonic() - started_at
        if elapsed >= timeout:
            raise LoggedError(
                "Timed out waiting for EngineX canonical rewind: expected "
                f"head {expected_hash}, observed {observed_hash} after "
                f"{attempts} polls ({elapsed:.3f}s)"
            )

        if attempts == 1 or attempts % 20 == 0:
            logger.info(
                "Waiting for canonical head %s; currently at %s "
                "(poll %d, %.3fs elapsed)",
                expected_hash,
                observed_hash,
                attempts,
                elapsed,
            )
        time.sleep(min(poll_interval, timeout - elapsed))


def test_blockchain_via_engine(
    timing_data: TimingData,
    eth_rpc: EthRPC,
    engine_rpc: EngineRPC,
    client: Client,
    genesis_verified_clients: set[str],
    block_rejection_tracker: BlockRejectionTracker,
    fixture: Union[BlockchainEngineFixture, BlockchainEngineXFixture],
    strict_exception_matching: bool,
    genesis_header: FixtureHeader,
) -> None:
    """
    Execute blockchain test fixtures against a client using the Engine API.

    This function supports both engine mode (`BlockchainEngineFixture`)
    with per-test clients and enginex mode (`BlockchainEngineXFixture`)
    with client reuse across tests sharing a pre-alloc group.

    Both modes follow the same test sequence for equivalence:

    1. Send initial FCU to genesis to establish the chain head.
    2. Verify the client genesis block hash matches genesis_header. Genesis
       is immutable per client, so in shared-client (enginex) mode this is
       done once per client and skipped for later tests in the group.
    3. Execute test fixture blocks using engine_newPayloadVX.
    4. For valid payloads, send FCU to advance the chain head.

    A client's bad-block cache persists across the tests of a pre-alloc
    group in enginex mode: a block that an earlier test already got
    rejected may be rejected again with a generic cache error (e.g. reth's
    "links to previously rejected block") instead of being re-validated.
    When the returned error does not match the expected exception, it is
    therefore verified against the error from the client's first rejection
    of the same block before failing the test.
    """
    with timing_data.time("Initial forkchoice update"):
        logger.info("Sending initial forkchoice update to genesis block...")
        try:
            response = engine_rpc.forkchoice_updated_with_retry(
                forkchoice_state=ForkchoiceState(
                    head_block_hash=genesis_header.block_hash,
                ),
                forkchoice_version=fixture.payloads[
                    0
                ].forkchoice_updated_version,
                max_attempts=30,
                wait_fixed=1.0,
            )
            if response.payload_status.status != PayloadStatusEnum.VALID:
                raise LoggedError(
                    f"Unexpected status on forkchoice updated to genesis: "
                    f"{response.payload_status.status}"
                )
        except ForkchoiceUpdateTimeoutError as e:
            raise LoggedError(
                f"Timed out waiting for forkchoice update to genesis: {e}"
            ) from None

    if isinstance(fixture, BlockchainEngineXFixture):
        with timing_data.time("Wait for canonical rewind"):
            wait_for_canonical_head(
                eth_rpc=eth_rpc,
                expected_head_hash=genesis_header.block_hash,
            )

    if client.id not in genesis_verified_clients:
        with timing_data.time("Get genesis block"):
            logger.info("Calling getBlockByNumber to get genesis block...")
            genesis_block = eth_rpc.get_block_by_number(0)
            assert genesis_block is not None, "genesis_block is None"
            if genesis_block["hash"] != str(genesis_header.block_hash):
                expected = genesis_header.block_hash
                got = genesis_block["hash"]
                logger.fail(
                    f"Genesis block hash mismatch. "
                    f"Expected: {expected}, Got: {got}"
                )
                raise GenesisBlockMismatchExceptionError(
                    expected_header=genesis_header,
                    got_genesis_block=genesis_block,
                )
        # Genesis is immutable per client, so verify it once per client. In
        # shared-client (enginex) mode the same client serves every test in a
        # pre-alloc group, so later tests skip the redundant getBlockByNumber
        # round-trip; per-test clients get a fresh id each test and re-verify.
        genesis_verified_clients.add(client.id)

    with timing_data.time("Payloads execution") as total_payload_timing:
        logger.info(
            f"Starting execution of {len(fixture.payloads)} payloads..."
        )
        for i, payload in enumerate(fixture.payloads):
            logger.info(
                f"Processing payload {i + 1}/{len(fixture.payloads)}..."
            )
            with total_payload_timing.time(
                f"Payload {i + 1}"
            ) as payload_timing:
                with payload_timing.time(
                    f"engine_newPayloadV{payload.new_payload_version}"
                ):
                    version = payload.new_payload_version
                    logger.info(f"Sending engine_newPayloadV{version}...")
                    try:
                        payload_response = engine_rpc.new_payload(
                            *payload.params,
                            version=payload.new_payload_version,
                        )
                        status = payload_response.status
                        logger.info(f"Payload response status: {status}")
                        expected_validity = (
                            PayloadStatusEnum.VALID
                            if payload.valid()
                            else PayloadStatusEnum.INVALID
                        )
                        if payload_response.status != expected_validity:
                            raise LoggedError(
                                f"unexpected status: want {expected_validity},"
                                f" got {payload_response.status}"
                            )
                        if payload.error_code is not None:
                            raise LoggedError(
                                "Client failed to raise expected Engine API "
                                f"error code: {payload.error_code}"
                            )
                        elif (
                            payload_response.status
                            == PayloadStatusEnum.INVALID
                        ):
                            if payload_response.validation_error is None:
                                raise LoggedError(
                                    "Client returned INVALID but no "
                                    "validation error was provided."
                                )
                            block_hash = payload.params[0].block_hash
                            first_rejection = block_rejection_tracker.track(
                                client.id,
                                block_hash,
                                payload_response.validation_error,
                            )
                            verify_block_rejection(
                                payload.validation_error,
                                payload_response.validation_error,
                                first_rejection,
                                block_hash,
                                strict_exception_matching,
                            )

                    except JSONRPCError as e:
                        logger.info(
                            f"JSONRPC error encountered: "
                            f"{e.code} - {e.message}"
                        )
                        if payload.error_code is None:
                            raise LoggedError(
                                f"Unexpected error: {e.code} - {e.message}"
                            ) from e
                        if e.code != payload.error_code:
                            raise LoggedError(
                                f"Unexpected error code: {e.code}, "
                                f"expected: {payload.error_code}"
                            ) from e

                if payload.valid():
                    with payload_timing.time(
                        f"engine_forkchoiceUpdatedV{payload.forkchoice_updated_version}"
                    ):
                        # Send a forkchoice update to the engine
                        version = payload.forkchoice_updated_version
                        logger.info(
                            f"Sending engine_forkchoiceUpdatedV{version}..."
                        )
                        forkchoice_response = engine_rpc.forkchoice_updated(
                            forkchoice_state=ForkchoiceState(
                                head_block_hash=payload.params[0].block_hash,
                            ),
                            payload_attributes=None,
                            version=payload.forkchoice_updated_version,
                        )
                        status = forkchoice_response.payload_status.status
                        logger.info(f"Forkchoice update response: {status}")
                        if (
                            forkchoice_response.payload_status.status
                            != PayloadStatusEnum.VALID
                        ):
                            status = forkchoice_response.payload_status.status
                            raise LoggedError(
                                f"unexpected status: want "
                                f"{PayloadStatusEnum.VALID}, got {status}"
                            )
        logger.info("All payloads processed successfully.")
