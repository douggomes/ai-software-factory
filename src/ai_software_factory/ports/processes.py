"""Narrow process execution port.

The application depends on this protocol and on immutable core models.  The
operating-system implementation lives under ``adapters.process``.
"""

from __future__ import annotations

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
