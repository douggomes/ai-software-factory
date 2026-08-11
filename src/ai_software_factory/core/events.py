"""Domain events — immutable records of significant occurrences.

Events are append-only, timestamped and carry correlation IDs for tracing.
They never contain secrets or provider-specific payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Final

from ai_software_factory.core.ids import AttemptId, RunId, TaskId

EVENT_SCHEMA_VERSION: Final[int] = 1


class EventType(Enum):
    """Types of domain events."""

    RUN_STARTED = auto()
    RUN_COMPLETED = auto()
    RUN_FAILED = auto()
    RUN_CANCELLED = auto()
    TASK_QUEUED = auto()
    TASK_STAGE_CHANGED = auto()
    TASK_SUCCEEDED = auto()
    TASK_FAILED = auto()
    TASK_CANCELLED = auto()
    ATTEMPT_STARTED = auto()
    ATTEMPT_COMPLETED = auto()
    ATTEMPT_FAILED = auto()
    FAILURE_NORMALIZED = auto()
    CONTINUATION_CREATED = auto()
    CONTINUATION_STARTED = auto()
    VALIDATION_SNAPSHOT = auto()
    REPAIR_STARTED = auto()
    REPAIR_COMPLETED = auto()
    HUMAN_APPROVAL_REQUESTED = auto()
    HUMAN_APPROVED = auto()
    HUMAN_REJECTED = auto()


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Immutable record of a domain occurrence.

    Carries correlation IDs (run_id, task_id, attempt_id) for tracing.
    The payload is a frozen dict of event-specific data.
    """

    event_type: EventType
    timestamp: datetime
    run_id: RunId
    task_id: TaskId | None = None
    attempt_id: AttemptId | None = None
    payload: dict[str, object] | None = None
    schema_version: int = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.payload is not None and type(self.payload) is not dict:
            raise TypeError("payload must be a dict or None")
