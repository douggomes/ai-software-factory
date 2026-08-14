"""Agent execution events — immutable records of agent activity.

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


class AgentEventType(Enum):
    """Types of agent execution events."""

    ATTEMPT_STARTED = auto()
    ATTEMPT_SUCCEEDED = auto()
    ATTEMPT_FAILED = auto()
    ATTEMPT_CANCELLED = auto()
    EDIT_PROPOSED = auto()
    EDIT_APPLIED = auto()
    EDIT_REJECTED = auto()
    TOOL_INVOKED = auto()
    TOOL_SUCCEEDED = auto()
    TOOL_FAILED = auto()


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """Immutable record of an agent execution occurrence.

    Carries correlation IDs (run_id, task_id, attempt_id) for tracing.
    The payload is a frozen dict of event-specific data.
    """

    event_type: AgentEventType
    timestamp: datetime
    run_id: RunId
    task_id: TaskId
    attempt_id: AttemptId
    payload: dict[str, object] | None = None
    schema_version: int = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.payload is not None and type(self.payload) is not dict:
            raise TypeError("payload must be a dict or None")


@dataclass(frozen=True, slots=True)
class EditProposed:
    """Payload for EDIT_PROPOSED event."""

    file_path: str
    original_content: str | None
    proposed_content: str
    reason: str


@dataclass(frozen=True, slots=True)
class EditApplied:
    """Payload for EDIT_APPLIED event."""

    file_path: str
    diff: str


@dataclass(frozen=True, slots=True)
class EditRejected:
    """Payload for EDIT_REJECTED event."""

    file_path: str
    reason: str


@dataclass(frozen=True, slots=True)
class ToolInvoked:
    """Payload for TOOL_INVOKED event."""

    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolSucceeded:
    """Payload for TOOL_SUCCEEDED event."""

    tool_name: str
    result_summary: str


@dataclass(frozen=True, slots=True)
class ToolFailed:
    """Payload for TOOL_FAILED event."""

    tool_name: str
    error: str


__all__ = [
    "AgentEvent",
    "AgentEventType",
    "EditApplied",
    "EditProposed",
    "EditRejected",
    "ToolFailed",
    "ToolInvoked",
    "ToolSucceeded",
]