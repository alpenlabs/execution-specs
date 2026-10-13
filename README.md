# Ethereum Execution Layer Specifications

## Alpen-maintained fork

This is Alpen Labs' fork of [ethereum/execution-specs][alpen-upstream],
used by [e2e-runner][alpen-runner]. It contains Alpen-maintained patches;
it is not an unchanged mirror. The upstream project documentation follows
this section.

### Which branch should I use?

- **Default / landing-page branch:** [`forks/amsterdam`][alpen-default].
  This is the upstream-based branch, not the patched EEST test source.
- **Maintained Prague test branch:**
  [`fix/alpen-prague-enginex-ci-20260916`][alpen-patches].
  This contains the patches used by the reviewed runner configuration.
- **Reviewed runner pin:**
  [`96e242bf7204ccf86fbb179387342834647a18d6`][alpen-pin].
  The runner uses this immutable commit, not the moving branch tip.
  README-only updates do not advance that pin.

The inherited `forks/amsterdam` name does not select the fork under test:
the reviewed runner lane selects **Prague**, including its transition fixtures.

### What we maintain here

At the reviewed pin, there are **16 patch commits** beyond upstream base
`6ba36d4907a746a5f08dc3a4577cb32221944fb1`. See the
[complete, pinned patch diff][alpen-diff]. These changes cover:

- EngineX client isolation and fixture chain-ID preservation.
- Isolation of mutable pre-allocations during fixture generation.
- Reth/Alpen error mapping for rejected transactions and blocks.
- Remote-execution funding, nonce handling and prestate setup, plus explicit
  capability markers for setups that remote execution cannot represent.
- A reference-spec MODEXP pointer-overflow fix and restored test coverage.
- Removal of non-semantic timeout/slow-test skips, and filtering an impossible
  zero-round BLAKE2F out-of-gas parameter combination before execution.

These are not all runner wrappers: the MODEXP patch changes the Python
reference implementation used to generate expected results. It needs explicit
review when updating the pin; do not describe this fork as unmodified upstream
conformance testing.

### Ownership and coverage boundary

This fork holds changes to the test framework, reference implementation and
test definitions. The dedicated `alpen-eest-client`, orchestration, CI,
Alpen exclusion policy and reporting live in **e2e-runner**, not here.
Canonical EngineX results do not establish live OL/DA/bridge integration or
SP1 proof coverage; those require separate production-stack validation.

Maintenance direction: upstream generally useful fixes, keep Alpen-specific
orchestration in e2e-runner, and retire patches once equivalent upstream
behavior is verified. A branch update alone is not approval to change the
runner pin: review the diff and rerun the relevant coverage gates first.

[alpen-upstream]: https://github.com/ethereum/execution-specs
[alpen-runner]: https://github.com/alpenlabs/e2e-runner
[alpen-default]: https://github.com/alpenlabs/execution-specs/tree/forks/amsterdam
[alpen-patches]: https://github.com/alpenlabs/execution-specs/tree/fix/alpen-prague-enginex-ci-20260916
[alpen-pin]: https://github.com/alpenlabs/execution-specs/commit/96e242bf7204ccf86fbb179387342834647a18d6
[alpen-diff]: https://github.com/alpenlabs/execution-specs/compare/6ba36d4907a746a5f08dc3a4577cb32221944fb1...96e242bf7204ccf86fbb179387342834647a18d6

## Upstream project

[![PyPI release](https://img.shields.io/pypi/v/ethereum-execution)](https://pypi.org/project/ethereum-execution/)
[![Tests release](https://img.shields.io/github/v/release/ethereum/execution-specs?filter=tests%40v%2A&label=tests)](https://github.com/ethereum/execution-specs/releases)
[![License](https://img.shields.io/github/license/ethereum/execution-specs)](LICENSE.md)
[![Python Specification](https://github.com/ethereum/execution-specs/actions/workflows/test.yaml/badge.svg)](https://github.com/ethereum/execution-specs/actions/workflows/test.yaml)
[![codecov](https://codecov.io/gh/ethereum/execution-specs/graph/badge.svg?token=0LQZO56RTM)](https://codecov.io/gh/ethereum/execution-specs)
![Python Versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

The Ethereum Execution Layer Specifications (EELS) are an executable Python reference implementation of Ethereum's execution layer, along with the test cases that verify it. It provides a shared, runnable description of consensus-critical behaviour, and the accompanying tests generate fixtures that can be used to validate execution client implementations.

## Quick Start

execution-specs uses [`uv`](https://docs.astral.sh/uv/) to manage the Python environment and dependencies, and [`just`](https://just.systems/) as a task runner for common commands (linting, building docs, generating fixtures). The commands below install both and set up the repo from scratch.

Requires a Unix-like shell. All platforms:

```console
git clone https://github.com/ethereum/execution-specs
cd execution-specs
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv python pin 3.12
uv sync
uv tool install --exclude-newer "10 days" rust-just
just shell-completions
```

Python 3.11–3.14 are supported; 3.12 tends to be the smoothest for local setup (pre-built wheels are available across the dependency set). For alternative `just` installation paths, macOS-specific installation notes, and troubleshooting, see [Installation](docs/getting_started/installation.md).

## Reference EVM CLI

`ethereum-spec-evm` — a `t8n` transition tool, `b11r` block builder, and state-test runner that execute the spec directly — is provided by the `ethereum-execution-testing` workspace package rather than by `ethereum-execution`. Within a checkout it is available as `uv run ethereum-spec-evm`; for standalone installation (e.g. in client CI or fuzzing setups), see [packages/testing/README.md](packages/testing/README.md).

## Documentation

- **Repo documentation (default branch/fork)**: <https://steel.ethereum.foundation/docs/execution-specs/>
- **Protocol history**: [docs/specs/protocol_history.md](docs/specs/protocol_history.md)
- **Versioning scheme**: [docs/specs/spec_releases.md](docs/specs/spec_releases.md) (PEP 440 compatible; hardfork encoded in the minor version, `rcN` marks devnets).

## Contributing

Earnest contributions are welcome; drive-by contributions are not. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to raise issues and pull requests. Further reading:

- [Code Standards](docs/getting_started/code_standards.md): Python coding preferences enforced in CI.
- [Verifying Changes](docs/getting_started/verifying_changes.md): Which local checks to run before opening a PR.
- [Writing Specs](docs/specs/writing_specs.md): Style rules and `ethereum_spec_tools` utilities for changes under `src/ethereum/`.
- [Writing Tests](docs/writing_tests/index.md): For guidance on adding consensus tests under `./tests/`.

The upstream project is maintained by the [STEEL Team](https://steel.ethereum.foundation/) at the Ethereum Foundation.

## Community and Support

Discussion around the initial specification of protocol changes happens on [Ethereum Magicians](https://ethereum-magicians.org/), in pull requests on [ethereum/EIPs](https://github.com/ethereum/EIPs), on the [Ethereum R&D Discord](https://discord.com/invite/qGpsxSA) (one of the channels in the *Execution R&D* category; for testing use `#el-testing`), and in the AllCoreDevs calls.

For tracking the status of upcoming Ethereum upgrades, see [Forkcast](https://forkcast.org/): EIP inclusion, client implementation progress, and ACD call summaries.

For other help, see the [Documentation](#documentation) section above, or reach out to one of the [STEEL team members](https://steel.ethereum.foundation/team/) in the Ethereum R&D Discord.

### Related projects

- [ethereum/EIPs](https://github.com/ethereum/EIPs): The prose EIP documents that EELS implements.
- [ethereum/execution-apis](https://github.com/ethereum/execution-apis): The JSON-RPC API specification, which lives in a separate repository.
- [ethereum/consensus-specs](https://github.com/ethereum/consensus-specs): The consensus-layer counterpart to this repository.

Production execution clients that implement the spec include [besu](https://github.com/besu-eth/besu), [erigon](https://github.com/erigontech/erigon), [ethrex](https://github.com/lambdaclass/ethrex), [geth](https://github.com/ethereum/go-ethereum), [nethermind](https://github.com/NethermindEth/nethermind), and [reth](https://github.com/paradigmxyz/reth).

## Responsible Disclosure of Vulnerabilities

> [!CAUTION]
> Care is required when filing issues or PRs for functionality that is live on Ethereum mainnet. Please report vulnerabilities and verify bounty eligibility via the [bug bounty program](https://bounty.ethereum.org); see [SECURITY.md](SECURITY.md) for details.
>
> - **Please do not create a PR with a vulnerability visible.**
> - **Please do not file a public ticket mentioning the vulnerability.**

## License

The Ethereum Execution Layer Specification is licensed under the [Creative Commons Zero v1.0 Universal](LICENSE.md).
