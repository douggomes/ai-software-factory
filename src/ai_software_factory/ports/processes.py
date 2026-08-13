"""Narrow process execution port.

The application depends on this protocol and on immutable core models.  The
operating-system implementation lives under ``adapters.process``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_software_factory.core.process_models import ProcessRequest, ProcessResult


class ProcessExecutionError(RuntimeError):
    """Base error for process execution failures."""


class ProcessPolicyError(ProcessExecutionError):
    """Raised when executable, cwd or environment policy rejects a request."""


class ProcessIsolationError(ProcessExecutionError):
    """Raised when untrusted code has no approved strong isolation."""


class ProcessArtifactError(ProcessExecutionError):
    """Raised when sanitized process output cannot be persisted."""


class IsolationProbeError(ProcessIsolationError):
    """Raised when a local OCI runtime or immutable image cannot be proven safe."""


class SnapshotAuthorizationError(ProcessIsolationError):
    """Raised when a request does not target one approved private snapshot."""


@runtime_checkable
class IsolationCapability(Protocol):
    """Opaque proof issued by one local isolation backend."""


@runtime_checkable
class IsolationBackend(Protocol):
    """Prove and authorize one local OCI isolation configuration."""

    async def probe(self) -> IsolationCapability:
        """Return a short-lived capability or fail before repository code can run."""
        ...

    def authorize(self, capability: IsolationCapability) -> IsolationCapability:
        """Validate and retain a capability bound to one local runtime probe."""
        ...

    def build_run_argv(
        self,
        capability: IsolationCapability,
        snapshot_root: Path,
        container_name: str,
        request: ProcessRequest,
    ) -> tuple[str, ...]:
        """Build the backend's complete, closed OCI invocation."""
        ...

    def build_cleanup_argv(
        self, capability: IsolationCapability, container_name: str
    ) -> tuple[str, ...]:
        """Build cleanup for exactly one execution-owned container identifier."""
        ...


@runtime_checkable
class SnapshotAuthorizer(Protocol):
    """Bind a process request to one verified private evaluation snapshot."""

    def authorize(self, requested_cwd: Path) -> Path:
        """Return the canonical snapshot root or raise before an OCI invocation."""
        ...


@runtime_checkable
class ProcessRunner(Protocol):
    """Execute one already-authorized process request.

    Host implementations retain stable executable bytes before spawn. Physical
    relocation is an explicit part of this contract and is bounded by
    ``ProcessPolicy``. Executables must receive resources by argv, environment
    or cwd; discovery relative to their physical executable path is unsupported.
    """

    async def run(self, request: ProcessRequest) -> ProcessResult:
        """Run a process and return a bounded, sanitized result."""
        ...
