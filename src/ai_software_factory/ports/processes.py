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
    """Execute one already-authorized process request."""

    async def run(self, request: ProcessRequest) -> ProcessResult:
        """Run a process and return a bounded, sanitized result."""
        ...
