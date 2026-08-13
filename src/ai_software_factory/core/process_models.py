"""Immutable process execution models and security policy values.

The core owns validation of process requests, while the adapter owns the
operating-system effects.  Keeping the policy in this module prevents a
subprocess adapter from silently widening the authority of its callers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol, cast

from ai_software_factory.core.ids import AttemptId, RunId

DEFAULT_TIMEOUT_SECONDS: Final[float] = 900.0
DEFAULT_TERMINATION_GRACE_SECONDS: Final[float] = 5.0
DEFAULT_MAX_OUTPUT_BYTES: Final[int] = 4_194_304
DEFAULT_MAX_EXECUTABLE_BYTES: Final[int] = 268_435_456
DEFAULT_CONTROLLED_PATH: Final[str] = "/usr/bin:/bin"
_ENVIRONMENT_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENVIRONMENT_KEYS: Final[frozenset[str]] = frozenset(
    {"HOME", "PATH", "TMP", "TEMP", "TMPDIR"}
)


def _empty_environment() -> dict[str, str]:
    return {}


class ProcessModelError(ValueError):
    """Base error for invalid process models."""


class TrustProfile(StrEnum):
    """Trust classification of the code that will be executed."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class ArtifactReference(Protocol):
    """Structural reference returned by an artifact adapter."""

    @property
    def run_id(self) -> RunId:
        """Owning run identity."""
        ...

    @property
    def relative_path(self) -> str:
        """Validated path relative to the run artifact root."""
        ...


@dataclass(frozen=True, slots=True)
class ProcessPolicy:
    """Allowlist and environment policy for one process invocation."""

    allowed_executables: tuple[Path, ...] = ()
    allowed_cwd_roots: tuple[Path, ...] = ()
    environment_allowlist: frozenset[str] = frozenset()
    controlled_path: str = DEFAULT_CONTROLLED_PATH
    max_executable_bytes: int = DEFAULT_MAX_EXECUTABLE_BYTES

    def __post_init__(self) -> None:
        executables = tuple(Path(path) for path in self.allowed_executables)
        cwd_roots = tuple(Path(path) for path in self.allowed_cwd_roots)
        environment_allowlist: frozenset[str] = frozenset(self.environment_allowlist)
        object.__setattr__(self, "allowed_executables", executables)
        object.__setattr__(self, "allowed_cwd_roots", cwd_roots)
        object.__setattr__(self, "environment_allowlist", environment_allowlist)
        if not self.controlled_path or "\x00" in self.controlled_path:
            raise ProcessModelError("controlled_path must be a non-empty safe string")
        if not 0 < self.max_executable_bytes <= DEFAULT_MAX_EXECUTABLE_BYTES:
            raise ProcessModelError("executable byte limit is outside policy")
        for name in self.environment_allowlist:
            _validate_environment_key(name, allow_reserved=False)


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    """Validated request crossing the process runner port.

    ``argv`` is passed as individual arguments to an exec-style subprocess;
    no shell parsing is ever applied.  The allowlists are intentionally empty
    by default, so a caller must explicitly authorize both executable and
    working-directory roots.
    """

    argv: tuple[str, ...]
    cwd: Path
    policy: ProcessPolicy = field(default_factory=ProcessPolicy)
    executable: Path | None = None
    environment: Mapping[str, str] = field(default_factory=_empty_environment)
    env: Mapping[str, str] | None = None
    allowed_executables: tuple[Path, ...] = ()
    allowed_cwd_roots: tuple[Path, ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    termination_grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    max_processes: int | None = None
    max_memory_bytes: int | None = None
    max_cpu_seconds: int | None = None
    trust_profile: TrustProfile = TrustProfile.TRUSTED
    redaction_secrets: tuple[str, ...] = ()
    run_id: RunId | None = None
    attempt_id: AttemptId | None = None

    def __post_init__(self) -> None:
        _validate_argv(self.argv)
        _normalize_request_paths(self)
        _normalize_request_environment(self)
        _normalize_request_policy(self)
        _normalize_request_profile(self)
        _validate_request_limits(self)
        _validate_request_environment(self)
        _validate_request_secrets(self)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Sanitized outcome of one process invocation.

    Raw stdout/stderr never cross this model boundary.  When an artifact
    store and run identity are supplied, the two references point to bounded,
    redacted artifacts; otherwise the streams are intentionally discarded.
    """

    exit_code: int | None
    signal: int | None
    duration_seconds: float
    truncated: bool
    timed_out: bool
    stdout_ref: ArtifactReference | None = None
    stderr_ref: ArtifactReference | None = None

    def __post_init__(self) -> None:
        if self.exit_code is not None and self.signal is not None:
            raise ProcessModelError("result cannot have both exit_code and signal")
        if self.exit_code is None and self.signal is None:
            raise ProcessModelError("result must have exit_code or signal")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ProcessModelError("duration_seconds must be finite and non-negative")

    @property
    def returncode(self) -> int:
        """Expose the conventional subprocess return code without raw output."""
        if self.exit_code is not None:
            return self.exit_code
        if self.signal is None:
            raise ProcessModelError("result has no termination status")
        return -self.signal

    @property
    def succeeded(self) -> bool:
        """Whether the process exited normally with status zero."""
        return self.exit_code == 0


def _normalize_request_paths(request: ProcessRequest) -> None:
    object.__setattr__(request, "cwd", Path(request.cwd))
    if request.executable is not None:
        object.__setattr__(request, "executable", Path(request.executable))


def _normalize_request_environment(request: ProcessRequest) -> None:
    if request.env is not None and request.environment:
        raise ProcessModelError("use either environment or env, not both")
    source = request.env if request.env is not None else request.environment
    environment: dict[str, str] = dict(source)
    object.__setattr__(request, "environment", MappingProxyType(environment))


def _normalize_request_policy(request: ProcessRequest) -> None:
    if not request.allowed_executables and not request.allowed_cwd_roots:
        return
    policy = request.policy
    object.__setattr__(
        request,
        "policy",
        ProcessPolicy(
            allowed_executables=request.allowed_executables or policy.allowed_executables,
            allowed_cwd_roots=request.allowed_cwd_roots or policy.allowed_cwd_roots,
            environment_allowlist=policy.environment_allowlist,
            controlled_path=policy.controlled_path,
            max_executable_bytes=policy.max_executable_bytes,
        ),
    )


def _normalize_request_profile(request: ProcessRequest) -> None:
    try:
        object.__setattr__(request, "trust_profile", TrustProfile(request.trust_profile))
    except ValueError as error:
        raise ProcessModelError(f"unsupported trust profile: {request.trust_profile!r}") from error


def _validate_request_limits(request: ProcessRequest) -> None:
    if not math.isfinite(request.timeout_seconds) or request.timeout_seconds <= 0:
        raise ProcessModelError("timeout_seconds must be finite and positive")
    if (
        not math.isfinite(request.termination_grace_seconds)
        or request.termination_grace_seconds <= 0
    ):
        raise ProcessModelError("termination_grace_seconds must be finite and positive")
    if request.max_output_bytes <= 0:
        raise ProcessModelError("max_output_bytes must be positive")
    _validate_optional_limit(request.max_processes, "max_processes")
    _validate_optional_limit(request.max_memory_bytes, "max_memory_bytes")
    _validate_optional_limit(request.max_cpu_seconds, "max_cpu_seconds")


def _validate_request_environment(request: ProcessRequest) -> None:
    for key, value in request.environment.items():
        _validate_environment_key(key, allow_reserved=False)
        if "\x00" in value:
            raise ProcessModelError(f"environment value contains NUL: {key}")


def _validate_request_secrets(request: ProcessRequest) -> None:
    for secret in request.redaction_secrets:
        if not secret or "\x00" in secret:
            raise ProcessModelError("redaction secrets must be non-empty and NUL-free")


def _validate_argv(argv: tuple[str, ...]) -> None:
    if type(argv) is not tuple or not argv:
        raise ProcessModelError("argv must be a non-empty tuple")
    typed_argv = cast(tuple[object, ...], argv)
    for argument in typed_argv:
        if type(argument) is not str or not argument or "\x00" in argument:
            raise ProcessModelError("argv entries must be non-empty NUL-free strings")


def _validate_environment_key(name: str, *, allow_reserved: bool) -> None:
    if not _ENVIRONMENT_KEY_PATTERN.fullmatch(name):
        raise ProcessModelError(f"invalid environment variable name: {name!r}")
    if not allow_reserved and name in _RESERVED_ENVIRONMENT_KEYS:
        raise ProcessModelError(f"reserved environment variable cannot be supplied: {name}")


def _validate_optional_limit(value: int | None, name: str) -> None:
    if value is not None and value <= 0:
        raise ProcessModelError(f"{name} must be positive when provided")
