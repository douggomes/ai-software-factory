"""Worker port — narrow interface for agent execution.

The application depends on this protocol and on immutable core models.  The
concrete adapters (fake, claude, codex, opencode) live under ``adapters.agents``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_software_factory.core.agent_events import AgentEvent
from ai_software_factory.core.ids import AttemptId, RunId, TaskId
from ai_software_factory.core.workspace_models import Workspace


class WorkerError(Exception):
    """Base class for worker port failures."""


class WorkerExecutionError(WorkerError):
    """Raised when a worker cannot produce events at all (not a task failure)."""


class WorkerPolicyError(WorkerError):
    """Raised when a worker request violates policy (e.g. disallowed path)."""


@dataclass(frozen=True, slots=True)
class AgentExecutionRequest:
    """Immutable request crossing the worker port.

    The application validates scope and policy before constructing this request.
    """

    run_id: RunId
    task_id: TaskId
    attempt_id: AttemptId
    workspace: Workspace
    spec_text: str
    allowed_paths: tuple[str, ...]


@runtime_checkable
class AgentWorker(Protocol):
    """Execute a task in an isolated workspace and emit typed events.

    Implementations must not perform Git commit/push/merge or network calls.
    Write authority is limited to the workspace worktree.
    """

    @property
    def worker_id(self) -> str:
        """Stable, non-secret identifier for this worker type (e.g. ``fake-success``)."""
        ...

    async def execute(self, request: AgentExecutionRequest) -> AsyncIterator[AgentEvent]:
        """Run the agent and yield a stream of typed events.

        The stream terminates with a terminal event (Succeeded/Failed/Cancelled).
        Never raises for a *failing* task — that is expressed via events.
        Raises ``WorkerExecutionError`` only when the worker itself cannot run.
        """
        ...


@dataclass(frozen=True, slots=True)
class WorkerCapability:
    """Opaque proof issued by a worker adapter during probe."""

    worker_id: str
    version: str
    capabilities: frozenset[str]


@runtime_checkable
class WorkerProbe(Protocol):
    """Prove a worker adapter is available and report its capabilities."""

    async def probe(self) -> WorkerCapability:
        """Return a capability or fail before repository code can run."""
        ...


__all__ = [
    "AgentExecutionRequest",
    "AgentWorker",
    "WorkerCapability",
    "WorkerError",
    "WorkerExecutionError",
    "WorkerPolicyError",
    "WorkerProbe",
]