"""
Pytest fixtures for the `consume enginex` simulator.

Configure the Hive back-end and EL clients for test execution with
`BlockchainEngineXFixtures`. Group lifecycle reuses clients that share a
pre-allocation group; test lifecycle starts a fresh client for every fixture.
"""

import io
import json
import logging
import time
from typing import TYPE_CHECKING, Generator, Literal, cast

import pytest
from hive.client import Client, ClientType
from hive.testing import HiveTest

from execution_testing.fixtures import BlockchainEngineXFixture
from execution_testing.fixtures.blockchain import FixtureHeader
from execution_testing.fixtures.pre_alloc_groups import PreAllocGroup

from ..helpers.test_tracker import (
    PreAllocGroupTestTracker,
    enginex_group_counts_key,
    make_group_identifier,
)

if TYPE_CHECKING:
    from ..multi_test_client import MultiTestClientManager
    from ..timing_data import TimingData

logger = logging.getLogger(__name__)

EngineXClientLifecycle = Literal["group", "test"]
ENGINE_X_CLIENT_LIFECYCLES: tuple[EngineXClientLifecycle, ...] = (
    "group",
    "test",
)
DEFAULT_ENGINE_X_CLIENT_LIFECYCLE: EngineXClientLifecycle = "group"

pytest_plugins = (
    "execution_testing.cli.pytest_commands.plugins.pytest_hive.pytest_hive",
    "execution_testing.cli.pytest_commands.plugins.consume.simulators.base",
    "execution_testing.cli.pytest_commands.plugins.consume.simulators.multi_test_client",
    "execution_testing.cli.pytest_commands.plugins.consume.simulators.test_case_description",
    "execution_testing.cli.pytest_commands.plugins.consume.simulators.timing_data",
    "execution_testing.cli.pytest_commands.plugins.consume.simulators.exceptions",
    "execution_testing.cli.pytest_commands.plugins.consume.simulators.helpers.test_tracker",
    "execution_testing.cli.pytest_commands.plugins.consume.simulators.engine_api",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the EngineX client lifecycle control."""
    group = parser.getgroup("enginex client lifecycle")
    group.addoption(
        "--enginex-client-lifecycle",
        choices=ENGINE_X_CLIENT_LIFECYCLES,
        default=DEFAULT_ENGINE_X_CLIENT_LIFECYCLE,
        help=(
            "Choose whether one execution client is reused for each "
            "pre-allocation group ('group') or a fresh client is started "
            "for every fixture ('test')."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Set the supported fixture formats for the enginex simulator."""
    config.supported_fixture_formats = [BlockchainEngineXFixture]  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def enginex_client_lifecycle(
    request: pytest.FixtureRequest,
) -> EngineXClientLifecycle:
    """Return the validated EngineX client lifecycle selected on the CLI."""
    value = request.config.getoption("enginex_client_lifecycle")
    if value not in ENGINE_X_CLIENT_LIFECYCLES:
        raise ValueError(f"Unsupported EngineX client lifecycle: {value!r}")
    return cast(EngineXClientLifecycle, value)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """
    Count tests per xdist_group and sort largest groups first.

    The xdist_group markers are set during parametrization in
    `pytest_generate_tests`. This hook reads them to count tests
    per group and sort for optimal xdist scheduling.

    Use `trylast=True` to run after test deselection
    (from `-k`, `-m` filters).
    """
    supported_formats = getattr(config, "supported_fixture_formats", [])
    if BlockchainEngineXFixture not in supported_formats:
        return

    group_counts: dict[str, int] = {}

    for item in items:
        for marker in item.iter_markers("xdist_group"):
            if "name" in marker.kwargs:
                group_identifier = marker.kwargs["name"]
                break
        else:
            continue
        group_counts[group_identifier] = (
            group_counts.get(group_identifier, 0) + 1
        )

    session.stash[enginex_group_counts_key] = group_counts
    logger.info(
        f"Counted {len(group_counts)} pre-alloc groups with "
        f"{sum(group_counts.values())} total tests"
    )

    def sort_key(item: pytest.Item) -> tuple[int, str]:
        """Return sort key: largest group first, then by group id."""
        for marker in item.iter_markers("xdist_group"):
            if "name" in marker.kwargs:
                gid = marker.kwargs["name"]
                return (-group_counts[gid], gid)
        return (0, "")

    items.sort(key=sort_key)
    logger.info("Sorted tests by pre-alloc group (largest first)")


class _GroupDispatchTracker:
    """
    Per-worker (per-process) tracker of the idle time between test protocols.

    The gap between the end of one test's run protocol and the start of the
    next test's protocol is time the xdist worker spends waiting for the
    controller (dispatch latency) at group boundaries. Small gaps may
    instead be ordinary inter-protocol overhead (e.g. report submission):
    the gap only equals dispatch latency when the worker's local item
    queue is empty.
    """

    last_group: str | None = None
    last_protocol_end: float | None = None


def _xdist_group_name(item: pytest.Item) -> str | None:
    """Return the xdist_group marker name of an item, if any."""
    for marker in item.iter_markers("xdist_group"):
        if "name" in marker.kwargs:
            return marker.kwargs["name"]
    return None


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Generator[None, None, None]:
    """Log a group-start marker with dispatch idle time at group boundaries."""
    del nextitem

    group = _xdist_group_name(item)
    if group is not None and group != _GroupDispatchTracker.last_group:
        if _GroupDispatchTracker.last_protocol_end is not None:
            idle_ms = (
                time.perf_counter() - _GroupDispatchTracker.last_protocol_end
            ) * 1000
            logger.info(
                f"⏱ phase=group_start group={group} idle_ms={idle_ms:.1f}"
            )
        else:
            logger.info(f"⏱ phase=group_start group={group}")
        _GroupDispatchTracker.last_group = group
    yield
    _GroupDispatchTracker.last_protocol_end = time.perf_counter()


@pytest.fixture(scope="session", autouse=True)
def _configure_client_manager(
    multi_test_client_manager: "MultiTestClientManager",
    pre_alloc_group_test_tracker: PreAllocGroupTestTracker,
) -> None:
    """Wire the test tracker to the client manager at session start."""
    multi_test_client_manager.set_test_tracker(pre_alloc_group_test_tracker)


@pytest.fixture(scope="module")
def test_suite_name() -> str:
    """The name of the hive test suite used in this simulator."""
    return "eels/consume-enginex"


@pytest.fixture(scope="module")
def test_suite_description() -> str:
    """The description of the hive test suite used in this simulator."""
    return (
        "Execute blockchain tests against clients using the Engine API with "
        "pre-allocation group optimization using Engine X fixtures."
    )


def _start_client(
    *,
    hive_context: HiveTest,
    client_type: ClientType,
    environment: dict,
    client_genesis: dict,
    group_identifier: str,
    total_timing_data: "TimingData",
) -> Client:
    """Start one EngineX client from a pre-allocation-group genesis."""
    serialize_start = time.perf_counter()
    genesis_bytes = json.dumps(client_genesis).encode("utf-8")
    buffered_genesis = io.BufferedReader(
        cast(io.RawIOBase, io.BytesIO(genesis_bytes))
    )
    logger.info(
        f"⏱ phase=genesis_serialize group={group_identifier} "
        f"ms={(time.perf_counter() - serialize_start) * 1000:.1f}"
    )
    logger.info(
        f"🚀 Starting client ({client_type.name}) for group {group_identifier}"
    )

    start_requested = time.perf_counter()
    with total_timing_data.time("Start client"):
        resolved_client = hive_context.start_client(
            client_type=client_type,
            environment=environment,
            files={"/genesis.json": buffered_genesis},
        )

    assert resolved_client is not None, (
        f"Unable to connect to client ({client_type.name}) via "
        "Hive. Check the client or Hive server logs for more information."
    )
    logger.info(
        f"⏱ phase=client_start group={group_identifier} "
        f"ms={(time.perf_counter() - start_requested) * 1000:.1f}"
    )
    logger.info(
        f"Client ({client_type.name}) ready for group {group_identifier}"
    )
    return resolved_client


@pytest.fixture(scope="function", autouse=True)
def _per_test_reporting(
    client: Client,
    hive_test: HiveTest,
    enginex_client_lifecycle: EngineXClientLifecycle,
) -> None:
    """
    Register grouped clients for per-test Hive log capture.

    Activate log segment capturing in the Hive backend for correct
    client log reporting in the multi-test client case.

    In grouped mode, parameter order matters: `client` listed before
    `hive_test` ensures pytest sets up `client` first and tears it down last.
    This guarantees `hive_test` teardown (`test.end()`) runs while the Hive
    node still exists, before grouped-client teardown marks the test complete.
    Isolated clients are already owned by the per-test `hive_test` context.
    """
    if enginex_client_lifecycle == "group":
        hive_test.register_multi_test_client(client)


@pytest.fixture(scope="function")
def _grouped_client(
    multi_test_hive_test: HiveTest,
    multi_test_client_manager: "MultiTestClientManager",
    fixture: BlockchainEngineXFixture,
    client_type: ClientType,
    environment: dict,
    client_genesis: dict,
    total_timing_data: "TimingData",
    request: pytest.FixtureRequest,
) -> Generator[Client, None, None]:
    """
    Get or create a multi-test client for this pre-allocation group.

    Called for each test, but reuses clients across tests that
    share the same pre-allocation group.
    """
    group_identifier = make_group_identifier(
        fixture.pre_hash, client_type.name
    )
    test_id = request.node.nodeid

    resolved_client = multi_test_client_manager.get_client(group_identifier)
    if resolved_client is not None:
        logger.info(f"♻️  Reusing client for group {group_identifier}")
    else:
        resolved_client = _start_client(
            hive_context=multi_test_hive_test,
            client_type=client_type,
            environment=environment,
            client_genesis=client_genesis,
            group_identifier=group_identifier,
            total_timing_data=total_timing_data,
        )

        multi_test_client_manager.register_client(
            group_identifier, resolved_client
        )
        resolved_client.multi_test = True

    try:
        yield resolved_client
    finally:
        multi_test_client_manager.mark_test_completed(
            group_identifier, test_id
        )


@pytest.fixture(scope="function")
def _isolated_client(
    hive_test: HiveTest,
    fixture: BlockchainEngineXFixture,
    client_type: ClientType,
    environment: dict,
    client_genesis: dict,
    total_timing_data: "TimingData",
) -> Generator[Client, None, None]:
    """Start and stop a fresh EngineX client for one fixture."""
    group_identifier = make_group_identifier(
        fixture.pre_hash, client_type.name
    )
    resolved_client = _start_client(
        hive_context=hive_test,
        client_type=client_type,
        environment=environment,
        client_genesis=client_genesis,
        group_identifier=group_identifier,
        total_timing_data=total_timing_data,
    )

    try:
        yield resolved_client
    finally:
        logger.info(
            f"🛑 Stopping isolated client for group {group_identifier}"
        )
        stop_started = time.perf_counter()
        try:
            resolved_client.stop()
        except Exception:
            logger.exception(
                "Failed to stop isolated client for group %s after %.1fms",
                group_identifier,
                (time.perf_counter() - stop_started) * 1000,
            )
            raise
        logger.info(
            f"⏱ phase=client_stop group={group_identifier} "
            f"ms={(time.perf_counter() - stop_started) * 1000:.1f}"
        )


@pytest.fixture(scope="function")
def client(
    request: pytest.FixtureRequest,
    enginex_client_lifecycle: EngineXClientLifecycle,
) -> Client:
    """Resolve the grouped or per-test EngineX client fixture."""
    fixture_name = (
        "_grouped_client"
        if enginex_client_lifecycle == "group"
        else "_isolated_client"
    )
    return cast(Client, request.getfixturevalue(fixture_name))


@pytest.fixture(scope="function")
def genesis_header(pre_alloc_group: PreAllocGroup) -> FixtureHeader:
    """Provide the genesis header from the pre-allocation group."""
    return pre_alloc_group.genesis
