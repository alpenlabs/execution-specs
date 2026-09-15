"""Tests for EngineX grouped and per-test client lifecycle modes."""

from collections.abc import Generator
from contextlib import nullcontext
from typing import Any, cast
from unittest.mock import Mock

import pytest

from ..simulators.enginex.conftest import (
    _isolated_client,
    client,
)

PLUGIN_MODULE = (
    "execution_testing.cli.pytest_commands.plugins.consume.simulators."
    "enginex.conftest"
)


@pytest.mark.parametrize("lifecycle", ["group", "test"])
def test_enginex_client_lifecycle_option(
    pytester: pytest.Pytester, lifecycle: str
) -> None:
    """Expose both supported lifecycle values through the pytest CLI."""
    pytester.makeconftest(
        f"from {PLUGIN_MODULE} import "
        "enginex_client_lifecycle, pytest_addoption\n"
    )
    pytester.makepyfile(
        f"""
        def test_selected_lifecycle(enginex_client_lifecycle):
            assert enginex_client_lifecycle == {lifecycle!r}
        """
    )

    result = pytester.runpytest(
        "-q", f"--enginex-client-lifecycle={lifecycle}"
    )

    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("lifecycle", "fixture_name"),
    [("group", "_grouped_client"), ("test", "_isolated_client")],
)
def test_client_routes_to_selected_lifecycle_fixture(
    lifecycle: str, fixture_name: str
) -> None:
    """Resolve exactly one lifecycle-specific client fixture."""
    request = Mock()
    selected_client = Mock()
    request.getfixturevalue.return_value = selected_client

    result = cast(Any, client).__wrapped__(request, lifecycle)

    assert result is selected_client
    request.getfixturevalue.assert_called_once_with(fixture_name)


def make_isolated_client_generator(
    *, client_stop_error: Exception | None = None
) -> tuple[Generator[Mock, None, None], Mock]:
    """Build one isolated-client fixture generator with mocked Hive I/O."""
    resolved_client = Mock()
    resolved_client.stop.side_effect = client_stop_error
    hive_test = Mock()
    hive_test.start_client.return_value = resolved_client
    fixture = Mock(pre_hash="0xprealloc")
    client_type = Mock(name="alpen")
    total_timing_data = Mock()
    total_timing_data.time.return_value = nullcontext()

    generator = cast(Any, _isolated_client).__wrapped__(
        hive_test=hive_test,
        fixture=fixture,
        client_type=client_type,
        environment={"HIVE_CHAIN_ID": "2892"},
        client_genesis={"alloc": {}},
        total_timing_data=total_timing_data,
    )
    return generator, resolved_client


def test_isolated_client_stops_after_each_fixture() -> None:
    """Never carry client state into the next EngineX fixture."""
    generator, resolved_client = make_isolated_client_generator()

    assert next(generator) is resolved_client
    with pytest.raises(StopIteration):
        next(generator)

    resolved_client.stop.assert_called_once_with()


def test_isolated_client_propagates_stop_failure() -> None:
    """Do not silently ignore a failed isolated-client teardown."""
    stop_error = RuntimeError("Hive failed to stop client")
    generator, resolved_client = make_isolated_client_generator(
        client_stop_error=stop_error
    )

    assert next(generator) is resolved_client
    with pytest.raises(RuntimeError, match="Hive failed to stop client"):
        next(generator)

    resolved_client.stop.assert_called_once_with()
