"""Persistence port — RunStore protocol for state and event persistence.

The RunStore is the authoritative source of truth for run state. State and
events are persisted atomically in the same transaction. The port uses only
domain types — no ORM or database-specific types leak into the interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ai_software_factory.core.events import DomainEvent
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, TaskExecution
from ai_software_factory.core.state_machine import Transition


class OptimisticLockError(Exception):
    """Raised when a transition conflicts with the current persisted state."""

    def __init__(self, task_id: TaskId, expected_stage: str, actual_stage: str) -> None:
        self.task_id = task_id
        self.expected_stage = expected_stage
        self.actual_stage = actual_stage
        super().__init__(
            f"optimistic lock conflict for task {task_id.value}: "
            f"expected {expected_stage}, found {actual_stage}"
        )


class RunNotFoundError(Exception):
    """Raised when a run cannot be found by its ID."""

    def __init__(self, run_id: RunId) -> None:
        self.run_id = run_id
        super().__init__(f"run not found: {run_id.value}")


class TaskExecutionNotFoundError(Exception):
    """Raised when a task execution cannot be found."""

    def __init__(self, run_id: RunId, task_id: TaskId) -> None:
        self.run_id = run_id
        self.task_id = task_id
        super().__init__(f"task execution not found: {task_id.value} in run {run_id.value}")


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Reconstructed run state from the persistence layer.

    Contains the run aggregate and its task executions. This is a pure
    domain snapshot with no dependency on NDJSON or external files.
    """

    run: Run
    task_executions: tuple[TaskExecution, ...]
    event_count: int


@runtime_checkable
class RunStore(Protocol):
    """Protocol for run state and event persistence.

    Implementations must guarantee atomic persistence of state and events
    in the same transaction. SQLite is the authoritative source of truth.
    """

    async def create_run(self, run: Run, event: DomainEvent) -> None:
        """Persist a new run and its creation event atomically."""
        ...

    async def create_task_execution(
        self, task_execution: TaskExecution, event: DomainEvent
    ) -> None:
        """Persist a new task execution and its event atomically."""
        ...

    async def transition(self, task_id: TaskId, transition: Transition) -> None:
        """Apply a state transition with optimistic version check.

        Raises OptimisticLockError if the current stage does not match
        the transition's from_stage.
        """
        ...

    async def load_run(self, run_id: RunId) -> RunSnapshot:
        """Reconstruct run state from the persistence layer.

        Raises RunNotFoundError if the run does not exist.
        """
        ...

    async def load_task_execution(self, run_id: RunId, task_id: TaskId) -> TaskExecution:
        """Load a single task execution by run and task IDs.

        Raises TaskExecutionNotFoundError if not found.
        """
        ...

    async def close(self) -> None:
        """Release any resources held by the store."""
        ...
