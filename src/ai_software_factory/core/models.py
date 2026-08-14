"""Domain entities — immutable aggregates representing runs, tasks and attempts.

These models have no dependency on infrastructure (ORM, providers, CLI).
They represent the core business concepts from the UML model in plan.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from ai_software_factory.core.ids import AttemptId, RunId, TaskId

#: Git commit SHA-1, hex.
_BASE_COMMIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
#: SHA-256 config hash, hex.
_CONFIG_HASH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SHA256_HEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class RunStatus(Enum):
    """Lifecycle status of a factory run."""

    QUEUED = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    CANCELLED = auto()


class TaskStage(Enum):
    """State machine stages for task execution."""

    QUEUED = auto()
    PREFLIGHT = auto()
    WORKSPACE_PREPARING = auto()
    CONTEXT_BUILDING = auto()
    PLANNING = auto()
    IMPLEMENTING = auto()
    NORMALIZING_FAILURE = auto()
    CREATING_CONTINUATION = auto()
    WAITING_FOR_CONTINUATION = auto()
    DETERMINISTIC_VALIDATION = auto()
    REVIEWING = auto()
    REPAIRING = auto()
    AWAITING_HUMAN_APPROVAL = auto()
    SUCCEEDED = auto()
    REJECTED = auto()
    ESCALATED = auto()
    FAILED = auto()
    CANCELLED = auto()


TERMINAL_STAGES: Final[frozenset[TaskStage]] = frozenset(
    {
        TaskStage.SUCCEEDED,
        TaskStage.REJECTED,
        TaskStage.ESCALATED,
        TaskStage.FAILED,
        TaskStage.CANCELLED,
    }
)


class AttemptKind(Enum):
    """Type of execution attempt."""

    INITIAL = auto()
    RETRY_SAME_WORKER = auto()
    FAILOVER_WORKER = auto()
    REPAIR = auto()
    CONTINUATION = auto()


@dataclass(frozen=True, slots=True)
class Run:
    """Top-level factory run — immutable aggregate root."""

    run_id: RunId
    spec_id: str
    base_commit: str
    status: RunStatus
    config_hash: str

    def __post_init__(self) -> None:
        if not _BASE_COMMIT_PATTERN.match(self.base_commit):
            raise ValueError(f"invalid base_commit format: {self.base_commit!r}")
        if not _CONFIG_HASH_PATTERN.match(self.config_hash):
            raise ValueError(f"invalid config_hash format: {self.config_hash!r}")


@dataclass(frozen=True, slots=True)
class TaskExecution:
    """Execution context for a single task within a run.

    Maintains identity (run_id, task_id, base_commit, worktree) across
    retry, failover and repair operations.
    """

    run_id: RunId
    task_id: TaskId
    base_commit: str
    worktree_path: str
    stage: TaskStage
    repair_count: int = 0
    failover_count: int = 0

    def __post_init__(self) -> None:
        if not _BASE_COMMIT_PATTERN.match(self.base_commit):
            raise ValueError(f"invalid base_commit format: {self.base_commit!r}")
        if self.repair_count < 0:
            raise ValueError(f"repair_count must be non-negative: {self.repair_count}")
        if self.failover_count < 0:
            raise ValueError(f"failover_count must be non-negative: {self.failover_count}")


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """Single attempt to execute a task (initial, retry, failover, repair)."""

    attempt_id: AttemptId
    task_execution: TaskExecution
    kind: AttemptKind
    worker_id: str
    parent_id: AttemptId | None = None


class RunOutcome(Enum):
    """Final outcome of a task execution."""

    SUCCEEDED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass(frozen=True, slots=True)
class RunReport:
    """Immutable report of a completed task execution.

    Contains identity, outcome, and references to diff, gate, and artifact evidence.
    """

    run_id: RunId
    task_id: TaskId
    attempt_id: AttemptId
    base_commit: str
    head_commit: str
    outcome: RunOutcome
    worker_id: str
    diff_hash: str
    gate_snapshot_id: str | None = None
    artifact_refs: tuple[str, ...] = ()
    created_at: str = ""

    def __post_init__(self) -> None:
        if not _BASE_COMMIT_PATTERN.match(self.base_commit):
            raise ValueError(f"invalid base_commit format: {self.base_commit!r}")
        if not _BASE_COMMIT_PATTERN.match(self.head_commit):
            raise ValueError(f"invalid head_commit format: {self.head_commit!r}")
        if not _SHA256_HEX_PATTERN.match(self.diff_hash):
            raise ValueError(f"invalid diff_hash format: {self.diff_hash!r}")
        if self.gate_snapshot_id is not None and not re.fullmatch(r"val-[a-z0-9]{12}", self.gate_snapshot_id):
            raise ValueError(f"invalid gate_snapshot_id format: {self.gate_snapshot_id!r}")
