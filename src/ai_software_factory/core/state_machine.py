"""State machine — pure, deterministic transitions for task execution.

This module implements the state machine from plan.md section 6.
All transitions are pure functions with no side effects. Invalid transitions
raise ``InvalidTransition`` without mutating the input state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.models import TERMINAL_STAGES, TaskStage


class InvalidTransitionError(Exception):
    """Raised when a transition is not allowed by the state machine."""

    def __init__(self, from_stage: TaskStage, event_type: EventType) -> None:
        self.from_stage = from_stage
        self.event_type = event_type
        super().__init__(f"invalid transition from {from_stage.name} on event {event_type.name}")


@dataclass(frozen=True, slots=True)
class Transition:
    """Result of a valid state transition."""

    from_stage: TaskStage
    to_stage: TaskStage
    event: DomainEvent


_TRANSITIONS: Final[dict[tuple[TaskStage, EventType], TaskStage]] = {
    (TaskStage.QUEUED, EventType.TASK_STAGE_CHANGED): TaskStage.PREFLIGHT,
    (TaskStage.QUEUED, EventType.TASK_CANCELLED): TaskStage.CANCELLED,
    (TaskStage.PREFLIGHT, EventType.TASK_STAGE_CHANGED): TaskStage.WORKSPACE_PREPARING,
    (TaskStage.PREFLIGHT, EventType.TASK_FAILED): TaskStage.ESCALATED,
    (TaskStage.WORKSPACE_PREPARING, EventType.TASK_STAGE_CHANGED): TaskStage.CONTEXT_BUILDING,
    (TaskStage.CONTEXT_BUILDING, EventType.TASK_STAGE_CHANGED): TaskStage.PLANNING,
    (TaskStage.PLANNING, EventType.TASK_STAGE_CHANGED): TaskStage.IMPLEMENTING,
    (TaskStage.IMPLEMENTING, EventType.TASK_STAGE_CHANGED): TaskStage.DETERMINISTIC_VALIDATION,
    (TaskStage.IMPLEMENTING, EventType.ATTEMPT_FAILED): TaskStage.NORMALIZING_FAILURE,
    (TaskStage.IMPLEMENTING, EventType.TASK_CANCELLED): TaskStage.CANCELLED,
    (TaskStage.NORMALIZING_FAILURE, EventType.ATTEMPT_STARTED): TaskStage.IMPLEMENTING,
    (
        TaskStage.NORMALIZING_FAILURE,
        EventType.CONTINUATION_CREATED,
    ): TaskStage.CREATING_CONTINUATION,
    (TaskStage.NORMALIZING_FAILURE, EventType.REPAIR_STARTED): TaskStage.REPAIRING,
    (TaskStage.NORMALIZING_FAILURE, EventType.TASK_FAILED): TaskStage.ESCALATED,
    (TaskStage.NORMALIZING_FAILURE, EventType.RUN_FAILED): TaskStage.FAILED,
    (
        TaskStage.CREATING_CONTINUATION,
        EventType.TASK_STAGE_CHANGED,
    ): TaskStage.WAITING_FOR_CONTINUATION,
    (TaskStage.WAITING_FOR_CONTINUATION, EventType.CONTINUATION_STARTED): TaskStage.IMPLEMENTING,
    (TaskStage.DETERMINISTIC_VALIDATION, EventType.TASK_STAGE_CHANGED): TaskStage.REVIEWING,
    (TaskStage.DETERMINISTIC_VALIDATION, EventType.TASK_SUCCEEDED): TaskStage.SUCCEEDED,
    (TaskStage.DETERMINISTIC_VALIDATION, EventType.REPAIR_STARTED): TaskStage.REPAIRING,
    (TaskStage.DETERMINISTIC_VALIDATION, EventType.TASK_CANCELLED): TaskStage.CANCELLED,
    (TaskStage.REVIEWING, EventType.HUMAN_APPROVAL_REQUESTED): TaskStage.AWAITING_HUMAN_APPROVAL,
    (TaskStage.REVIEWING, EventType.REPAIR_STARTED): TaskStage.REPAIRING,
    (TaskStage.REPAIRING, EventType.TASK_STAGE_CHANGED): TaskStage.DETERMINISTIC_VALIDATION,
    (TaskStage.REPAIRING, EventType.TASK_FAILED): TaskStage.ESCALATED,
    (TaskStage.AWAITING_HUMAN_APPROVAL, EventType.HUMAN_APPROVED): TaskStage.SUCCEEDED,
    (TaskStage.AWAITING_HUMAN_APPROVAL, EventType.HUMAN_REJECTED): TaskStage.REJECTED,
}


def transition(state: TaskStage, event: DomainEvent) -> Transition:
    """Compute the next state for a given stage and event.

    Pure function — never mutates the input. Raises ``InvalidTransition``
    if the transition is not allowed. Terminal stages accept no events.
    """
    if state in TERMINAL_STAGES:
        raise InvalidTransitionError(state, event.event_type)

    key = (state, event.event_type)
    next_stage = _TRANSITIONS.get(key)
    if next_stage is None:
        raise InvalidTransitionError(state, event.event_type)

    return Transition(from_stage=state, to_stage=next_stage, event=event)


def is_terminal(stage: TaskStage) -> bool:
    """Check if a stage is terminal (no further transitions allowed)."""
    return stage in TERMINAL_STAGES


def all_transitions() -> dict[tuple[TaskStage, EventType], TaskStage]:
    """Return a copy of the complete transition table."""
    return dict(_TRANSITIONS)
