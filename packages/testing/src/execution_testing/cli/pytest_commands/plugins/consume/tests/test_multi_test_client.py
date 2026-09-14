"""Tests for EngineX multi-test client configuration."""

from execution_testing.base_types import ZeroPaddedHexNumber

from ..simulators.multi_test_client import chain_id_environment


def test_chain_id_environment_uses_pre_alloc_group_chain_id() -> None:
    """EngineX clients must execute under the chain used to fill fixtures."""
    assert chain_id_environment(ZeroPaddedHexNumber(2892)) == {
        "HIVE_CHAIN_ID": "2892",
        "HIVE_NETWORK_ID": "2892",
    }
