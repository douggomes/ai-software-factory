"""Closed validation profile registry.

Profiles are fixed at import time — :func:`resolve_profile` accepts only a
name already present in the registry built by :func:`build_registry`. SPEC
commands are validated independently and must exactly match the registered
configuration; repository content can never expand executable authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ai_software_factory.core.process_models import ProcessPolicy
from ai_software_factory.evaluation.gates import CommandGate, DiffGate, ScopeGate, SecretGate
from ai_software_factory.ports.processes import ProcessRunner
from ai_software_factory.ports.validation import ValidationGate

_STRUCTURAL_GATES: Final[tuple[ValidationGate, ...]] = (ScopeGate(), DiffGate(), SecretGate())
_TEST_PROFILE_COMMANDS: Final[tuple[tuple[str, ...], ...]] = (
    ("uv", "run", "python", "-m", "compileall", "-q", "src", "tests"),
    ("uv", "run", "ruff", "check", "src", "tests"),
    ("uv", "run", "pyright", "src", "tests"),
    ("uv", "run", "pytest"),
)
_TEST_PROFILE_GATE_NAMES: Final[tuple[str, ...]] = ("compile", "lint", "types", "tests")


class ProfileNotRegisteredError(ValueError):
    """Raised when ``--profile`` does not name a registered profile."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"validation profile not registered: {name!r}")


class ProfileConfigurationError(ValueError):
    """Raised when SPEC commands do not match a registered safe profile."""


@dataclass(frozen=True, slots=True)
class ValidationProfile:
    """Immutable, closed sequence of gates executed in stable declared order."""

    name: str
    gates: tuple[ValidationGate, ...]

    @property
    def config_hash(self) -> str:
        definition = "\n".join(gate.configuration_key for gate in self.gates)
        return hashlib.sha256(f"{self.name}\n{definition}".encode()).hexdigest()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ValidationProfile.name must be non-empty")
        if not self.gates:
            raise ValueError("ValidationProfile.gates must be non-empty")


def _python_command_gates(
    uv_executable: Path,
    process_runner: ProcessRunner,
    process_policy: ProcessPolicy,
    validation_commands: tuple[tuple[str, ...], ...],
) -> tuple[ValidationGate, ...]:
    """The ``compile, lint, types, tests`` stages of the default gate order.

    Every command runs through the resolved ``uv`` executable only — argv is
    registered here in code. SPEC argv must match the registration exactly
    before the canonical executable and offline flag are injected.
    """
    if validation_commands != _TEST_PROFILE_COMMANDS:
        raise ProfileConfigurationError(
            "SPEC validation commands do not match registered profile 'tests'"
        )
    if not uv_executable.is_absolute():
        raise ProfileConfigurationError("resolved uv executable must be absolute")
    # OCI receives only fixed in-container command names. The composition root
    # separately validates the host ``uv_executable`` before this profile is built.
    uv = "uv"
    gates = (
        CommandGate(
            gate_name="compile",
            argv=(uv, "run", "--offline", *validation_commands[0][2:]),
            process_runner=process_runner,
            process_policy=process_policy,
        ),
        CommandGate(
            gate_name="lint",
            argv=(uv, "run", "--offline", *validation_commands[1][2:]),
            process_runner=process_runner,
            process_policy=process_policy,
        ),
        CommandGate(
            gate_name="types",
            argv=(uv, "run", "--offline", *validation_commands[2][2:]),
            process_runner=process_runner,
            process_policy=process_policy,
        ),
        CommandGate(
            gate_name="tests",
            argv=(uv, "run", "--offline", *validation_commands[3][2:]),
            process_runner=process_runner,
            process_policy=process_policy,
        ),
    )
    if tuple(gate.name for gate in gates) != _TEST_PROFILE_GATE_NAMES:
        raise ProfileConfigurationError("registered profile gate order is invalid")
    return gates


def build_registry(
    uv_executable: Path,
    process_runner: ProcessRunner,
    process_policy: ProcessPolicy,
    validation_commands: tuple[tuple[str, ...], ...],
) -> Mapping[str, ValidationProfile]:
    """Build the closed profile registry for one resolved ``uv`` executable.

    ``uv_executable`` is resolved once by the composition root (the CLI) so
    every ``CommandGate`` argv is anchored to an authorized, canonical path
    rather than a bare, PATH-searched name.
    """
    return {
        "tests": ValidationProfile(
            name="tests",
            gates=_STRUCTURAL_GATES
            + _python_command_gates(
                uv_executable,
                process_runner,
                process_policy,
                validation_commands,
            ),
        ),
    }


def resolve_profile(
    name: str,
    *,
    uv_executable: Path,
    process_runner: ProcessRunner,
    process_policy: ProcessPolicy,
    validation_commands: tuple[tuple[str, ...], ...],
) -> ValidationProfile:
    """Resolve a registered profile by name — never an ad-hoc command list."""
    if name != "tests":
        raise ProfileNotRegisteredError(name)
    registry = build_registry(
        uv_executable,
        process_runner,
        process_policy,
        validation_commands,
    )
    profile = registry.get(name)
    if profile is None:  # pragma: no cover - registry invariant guarded above
        raise ProfileNotRegisteredError(name)
    return profile
