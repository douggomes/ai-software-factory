"""Tests for the domain state machine — all transitions and invariants.

AC-001: All documented transitions have deterministic tests.
AC-002: Terminal stages, unknown events and identity mismatches fail without mutation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import AttemptId, RunId, TaskId
from ai_software_factory.core.models import TERMINAL_STAGES, TaskStage
from ai_software_factory.core.state_machine import (
    InvalidTransitionError,
    Transition,
    all_transitions,
    is_terminal,
    transition,
)


def _make_event(event_type: EventType) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        run_id=RunId("run-abcdefghijk1"),
        task_id=TaskId("TASK-001"),
    )


class TestAllTransitionsAndTerminalInvariants:
    """AC-001: 100% of the transition table is exercised."""

    def test_all_transitions_and_terminal_invariants(self) -> None:
        table = all_transitions()
        for (from_stage, event_type), expected_to in table.items():
            event = _make_event(event_type)
            result = transition(from_stage, event)
            assert isinstance(result, Transition)
            assert result.from_stage == from_stage
            assert result.to_stage == expected_to
            assert result.event is event

    def test_queued_to_preflight(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.QUEUED, event)
        assert result.to_stage == TaskStage.PREFLIGHT

    def test_queued_to_cancelled(self) -> None:
        event = _make_event(EventType.TASK_CANCELLED)
        result = transition(TaskStage.QUEUED, event)
        assert result.to_stage == TaskStage.CANCELLED

    def test_preflight_to_workspace_preparing(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.PREFLIGHT, event)
        assert result.to_stage == TaskStage.WORKSPACE_PREPARING

    def test_preflight_to_escalated(self) -> None:
        event = _make_event(EventType.TASK_FAILED)
        result = transition(TaskStage.PREFLIGHT, event)
        assert result.to_stage == TaskStage.ESCALATED

    def test_workspace_preparing_to_context_building(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.WORKSPACE_PREPARING, event)
        assert result.to_stage == TaskStage.CONTEXT_BUILDING

    def test_context_building_to_planning(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.CONTEXT_BUILDING, event)
        assert result.to_stage == TaskStage.PLANNING

    def test_planning_to_implementing(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.PLANNING, event)
        assert result.to_stage == TaskStage.IMPLEMENTING

    def test_implementing_to_deterministic_validation(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.IMPLEMENTING, event)
        assert result.to_stage == TaskStage.DETERMINISTIC_VALIDATION

    def test_implementing_to_normalizing_failure(self) -> None:
        event = _make_event(EventType.ATTEMPT_FAILED)
        result = transition(TaskStage.IMPLEMENTING, event)
        assert result.to_stage == TaskStage.NORMALIZING_FAILURE

    def test_implementing_to_cancelled(self) -> None:
        event = _make_event(EventType.TASK_CANCELLED)
        result = transition(TaskStage.IMPLEMENTING, event)
        assert result.to_stage == TaskStage.CANCELLED

    def test_normalizing_failure_retry_same_worker(self) -> None:
        event = _make_event(EventType.ATTEMPT_STARTED)
        result = transition(TaskStage.NORMALIZING_FAILURE, event)
        assert result.to_stage == TaskStage.IMPLEMENTING

    def test_normalizing_failure_to_creating_continuation(self) -> None:
        event = _make_event(EventType.CONTINUATION_CREATED)
        result = transition(TaskStage.NORMALIZING_FAILURE, event)
        assert result.to_stage == TaskStage.CREATING_CONTINUATION

    def test_normalizing_failure_to_repairing(self) -> None:
        event = _make_event(EventType.REPAIR_STARTED)
        result = transition(TaskStage.NORMALIZING_FAILURE, event)
        assert result.to_stage == TaskStage.REPAIRING

    def test_normalizing_failure_to_escalated(self) -> None:
        event = _make_event(EventType.TASK_FAILED)
        result = transition(TaskStage.NORMALIZING_FAILURE, event)
        assert result.to_stage == TaskStage.ESCALATED

    def test_normalizing_failure_to_failed(self) -> None:
        event = _make_event(EventType.RUN_FAILED)
        result = transition(TaskStage.NORMALIZING_FAILURE, event)
        assert result.to_stage == TaskStage.FAILED

    def test_creating_continuation_to_waiting(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.CREATING_CONTINUATION, event)
        assert result.to_stage == TaskStage.WAITING_FOR_CONTINUATION

    def test_waiting_for_continuation_to_implementing(self) -> None:
        event = _make_event(EventType.CONTINUATION_STARTED)
        result = transition(TaskStage.WAITING_FOR_CONTINUATION, event)
        assert result.to_stage == TaskStage.IMPLEMENTING

    def test_deterministic_validation_to_reviewing(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.DETERMINISTIC_VALIDATION, event)
        assert result.to_stage == TaskStage.REVIEWING

    def test_deterministic_validation_to_succeeded(self) -> None:
        event = _make_event(EventType.TASK_SUCCEEDED)
        result = transition(TaskStage.DETERMINISTIC_VALIDATION, event)
        assert result.to_stage == TaskStage.SUCCEEDED

    def test_deterministic_validation_to_repairing(self) -> None:
        event = _make_event(EventType.REPAIR_STARTED)
        result = transition(TaskStage.DETERMINISTIC_VALIDATION, event)
        assert result.to_stage == TaskStage.REPAIRING

    def test_deterministic_validation_to_cancelled(self) -> None:
        event = _make_event(EventType.TASK_CANCELLED)
        result = transition(TaskStage.DETERMINISTIC_VALIDATION, event)
        assert result.to_stage == TaskStage.CANCELLED

    def test_reviewing_to_awaiting_human_approval(self) -> None:
        event = _make_event(EventType.HUMAN_APPROVAL_REQUESTED)
        result = transition(TaskStage.REVIEWING, event)
        assert result.to_stage == TaskStage.AWAITING_HUMAN_APPROVAL

    def test_reviewing_to_repairing(self) -> None:
        event = _make_event(EventType.REPAIR_STARTED)
        result = transition(TaskStage.REVIEWING, event)
        assert result.to_stage == TaskStage.REPAIRING

    def test_repairing_to_deterministic_validation(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.REPAIRING, event)
        assert result.to_stage == TaskStage.DETERMINISTIC_VALIDATION

    def test_repairing_to_escalated(self) -> None:
        event = _make_event(EventType.TASK_FAILED)
        result = transition(TaskStage.REPAIRING, event)
        assert result.to_stage == TaskStage.ESCALATED

    def test_awaiting_human_approval_to_succeeded(self) -> None:
        event = _make_event(EventType.HUMAN_APPROVED)
        result = transition(TaskStage.AWAITING_HUMAN_APPROVAL, event)
        assert result.to_stage == TaskStage.SUCCEEDED

    def test_awaiting_human_approval_to_rejected(self) -> None:
        event = _make_event(EventType.HUMAN_REJECTED)
        result = transition(TaskStage.AWAITING_HUMAN_APPROVAL, event)
        assert result.to_stage == TaskStage.REJECTED

    def test_terminal_stages_are_complete(self) -> None:
        expected = {
            TaskStage.SUCCEEDED,
            TaskStage.REJECTED,
            TaskStage.ESCALATED,
            TaskStage.FAILED,
            TaskStage.CANCELLED,
        }
        assert expected == TERMINAL_STAGES

    def test_all_non_terminal_stages_have_transitions(self) -> None:
        table = all_transitions()
        sources = {stage for stage, _ in table}
        for stage in TaskStage:
            if stage not in TERMINAL_STAGES:
                assert stage in sources, f"{stage.name} has no outgoing transitions"


class TestInvalidTransitionIsAtomic:
    """AC-002: Invalid transitions fail without mutating the original state."""

    def test_invalid_transition_is_atomic(self) -> None:
        original_stage = TaskStage.QUEUED
        event = _make_event(EventType.HUMAN_APPROVED)

        with pytest.raises(InvalidTransitionError) as exc_info:
            transition(original_stage, event)

        assert exc_info.value.from_stage == original_stage
        assert exc_info.value.event_type == event.event_type

    @pytest.mark.parametrize("terminal", list(TERMINAL_STAGES))
    def test_terminal_stage_rejects_all_events(self, terminal: TaskStage) -> None:
        for event_type in EventType:
            event = _make_event(event_type)
            with pytest.raises(InvalidTransitionError):
                transition(terminal, event)

    def test_unknown_event_type_raises(self) -> None:
        event = _make_event(EventType.RUN_STARTED)
        with pytest.raises(InvalidTransitionError):
            transition(TaskStage.QUEUED, event)

    def test_wrong_event_for_stage_raises(self) -> None:
        event = _make_event(EventType.HUMAN_APPROVED)
        with pytest.raises(InvalidTransitionError):
            transition(TaskStage.IMPLEMENTING, event)

    def test_transition_result_is_immutable(self) -> None:
        event = _make_event(EventType.TASK_STAGE_CHANGED)
        result = transition(TaskStage.QUEUED, event)

        with pytest.raises(AttributeError):
            result.to_stage = TaskStage.FAILED  # type: ignore[misc]


class TestIdentityObjects:
    """Value objects are immutable, non-interchangeable and serializable."""

    def test_run_id_is_immutable(self) -> None:
        rid = RunId("run-abcdefghijk1")
        with pytest.raises(AttributeError):
            rid.value = "hacked"  # type: ignore[misc]

    def test_run_id_validates_format(self) -> None:
        RunId("run-abcdefghijk1")
        with pytest.raises(ValueError, match="invalid RunId"):
            RunId("bad-format")

    def test_task_id_is_immutable(self) -> None:
        tid = TaskId("TASK-001")
        with pytest.raises(AttributeError):
            tid.value = "hacked"  # type: ignore[misc]

    def test_task_id_validates_format(self) -> None:
        tid = TaskId("TASK-001")
        assert tid.ordinal == 1
        with pytest.raises(ValueError, match="invalid TaskId"):
            TaskId("TASK-1")

    def test_attempt_id_is_immutable(self) -> None:
        aid = AttemptId("att-abcdefghijk1")
        with pytest.raises(AttributeError):
            aid.value = "hacked"  # type: ignore[misc]

    def test_attempt_id_validates_format(self) -> None:
        AttemptId("att-abcdefghijk1")
        with pytest.raises(ValueError, match="invalid AttemptId"):
            AttemptId("bad")

    def test_ids_are_not_interchangeable(self) -> None:
        rid = RunId("run-abcdefghijk1")
        tid = TaskId("TASK-001")
        aid = AttemptId("att-abcdefghijk1")

        assert rid != tid  # type: ignore[comparison-overlap]
        assert rid != aid  # type: ignore[comparison-overlap]
        assert tid != aid  # type: ignore[comparison-overlap]

    def test_ids_are_hashable(self) -> None:
        rid = RunId("run-abcdefghijk1")
        tid = TaskId("TASK-001")
        aid = AttemptId("att-abcdefghijk1")

        d: dict[object, str] = {rid: "run", tid: "task", aid: "attempt"}
        assert d[rid] == "run"
        assert d[tid] == "task"
        assert d[aid] == "attempt"

    def test_ids_with_same_value_are_equal(self) -> None:
        assert RunId("run-abcdefghijk1") == RunId("run-abcdefghijk1")
        assert TaskId("TASK-001") == TaskId("TASK-001")
        assert AttemptId("att-abcdefghijk1") == AttemptId("att-abcdefghijk1")


class TestIsTerminal:
    def test_terminal_stages(self) -> None:
        for stage in TERMINAL_STAGES:
            assert is_terminal(stage) is True

    def test_non_terminal_stages(self) -> None:
        for stage in TaskStage:
            if stage not in TERMINAL_STAGES:
                assert is_terminal(stage) is False


class TestDomainEvent:
    def test_event_is_immutable(self) -> None:
        event = _make_event(EventType.RUN_STARTED)
        with pytest.raises(AttributeError):
            event.event_type = EventType.RUN_FAILED  # type: ignore[misc]

    def test_event_requires_dict_payload(self) -> None:
        with pytest.raises(TypeError, match="payload must be a dict"):
            DomainEvent(
                event_type=EventType.RUN_STARTED,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                run_id=RunId("run-abcdefghijk1"),
                payload="not a dict",  # type: ignore[arg-type]
            )

    def test_event_accepts_none_payload(self) -> None:
        event = DomainEvent(
            event_type=EventType.RUN_STARTED,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            run_id=RunId("run-abcdefghijk1"),
            payload=None,
        )
        assert event.payload is None

    def test_event_accepts_dict_payload(self) -> None:
        event = DomainEvent(
            event_type=EventType.RUN_STARTED,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            run_id=RunId("run-abcdefghijk1"),
            payload={"key": "value"},
        )
        assert event.payload == {"key": "value"}
