"""Integration tests for aif status / aif events (TASK-005 AC-003)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore
from ai_software_factory.application.queries import (
    RunStatusView,
    TaskStatusView,
    format_events_ndjson,
    format_run_status_json,
)
from ai_software_factory.cli import main
from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.state_machine import Transition

_SEEDED_EVENT_COUNT: Final[int] = 3
_WORKTREE_PATH: Final[str] = "/worktrees/test-status-cli"


async def _seed_run(db_path: Path) -> RunId:
    store = await SQLiteRunStore.create(db_path)
    run_id = RunId("run-statuscli001")
    run = Run(
        run_id=run_id,
        spec_id="spec-cli",
        base_commit="c" * 40,
        status=RunStatus.RUNNING,
        config_hash="d" * 64,
    )
    started_at = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
    await store.create_run(
        run,
        DomainEvent(
            event_type=EventType.RUN_STARTED,
            timestamp=started_at,
            run_id=run_id,
            payload={"source": "test"},
        ),
    )
    task = TaskExecution(
        run_id=run_id,
        task_id=TaskId("TASK-005"),
        base_commit="c" * 40,
        worktree_path=_WORKTREE_PATH,
        stage=TaskStage.QUEUED,
    )
    await store.create_task_execution(
        task,
        DomainEvent(
            event_type=EventType.TASK_QUEUED,
            timestamp=datetime(2026, 8, 11, 12, 0, 1, tzinfo=UTC),
            run_id=run_id,
            task_id=task.task_id,
        ),
    )
    await store.transition(
        run_id,
        task.task_id,
        Transition(
            from_stage=TaskStage.QUEUED,
            to_stage=TaskStage.PREFLIGHT,
            event=DomainEvent(
                event_type=EventType.TASK_STAGE_CHANGED,
                timestamp=datetime(2026, 8, 11, 12, 0, 2, tzinfo=UTC),
                run_id=run_id,
                task_id=task.task_id,
                payload={"to": "PREFLIGHT"},
            ),
        ),
    )
    await store.close()
    return run_id


def test_status_and_events_survive_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-003: status JSON and NDJSON export are stable across CLI reopen."""
    home = tmp_path / "aif-home"
    home.mkdir()
    db_path = home / "state.db"
    run_id = asyncio.run(_seed_run(db_path))
    monkeypatch.setenv("AIF_FACTORY_HOME", str(home))

    code1 = main(["status", run_id.value, "--json"])
    out1 = capsys.readouterr().out
    assert code1 == 0
    payload1 = json.loads(out1)
    assert payload1["run_id"] == run_id.value
    assert payload1["status"] == "RUNNING"
    assert payload1["event_count"] == _SEEDED_EVENT_COUNT
    assert payload1["tasks"][0]["task_id"] == "TASK-005"
    assert payload1["tasks"][0]["stage"] == "PREFLIGHT"

    code2 = main(["status", run_id.value, "--json"])
    out2 = capsys.readouterr().out
    assert code2 == 0
    assert out2 == out1

    code_e1 = main(["events", run_id.value])
    events1 = capsys.readouterr().out
    assert code_e1 == 0
    lines = [line for line in events1.splitlines() if line]
    assert len(lines) == _SEEDED_EVENT_COUNT
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["event_type"] == "RUN_STARTED"
    assert parsed[1]["event_type"] == "TASK_QUEUED"
    assert parsed[2]["event_type"] == "TASK_STAGE_CHANGED"
    assert parsed[0]["timestamp"].endswith("+00:00")

    code_e2 = main(["events", run_id.value])
    events2 = capsys.readouterr().out
    assert code_e2 == 0
    assert events2 == events1

    stale = home / "runs" / run_id.value / "events.ndjson"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale\n", encoding="utf-8")
    code_e3 = main(["events", run_id.value])
    events3 = capsys.readouterr().out
    assert code_e3 == 0
    assert events3 == events1


def test_format_helpers_are_byte_stable() -> None:
    view = RunStatusView(
        run_id="run-abc123def456",
        spec_id="s",
        base_commit="a" * 40,
        status="QUEUED",
        config_hash="b" * 64,
        event_count=1,
        tasks=(
            TaskStatusView(
                task_id="TASK-001",
                stage="QUEUED",
                base_commit="a" * 40,
                worktree_path="/worktrees/test",
                repair_count=0,
                failover_count=0,
            ),
        ),
    )
    first = format_run_status_json(view)
    second = format_run_status_json(view)
    assert first == second
    assert first.endswith("\n")

    event = DomainEvent(
        event_type=EventType.RUN_STARTED,
        timestamp=datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=UTC),
        run_id=RunId("run-abc123def456"),
        payload={"k": 1},
    )
    nd1 = format_events_ndjson([event])
    nd2 = format_events_ndjson([event])
    assert nd1 == nd2
    assert nd1.endswith("\n")
    assert '"event_type":"RUN_STARTED"' in nd1


def test_status_missing_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "empty-home"
    home.mkdir()
    db_path = home / "state.db"

    async def _init() -> None:
        store = await SQLiteRunStore.create(db_path)
        await store.close()

    asyncio.run(_init())
    monkeypatch.setenv("AIF_FACTORY_HOME", str(home))
    code = main(["status", "run-missing0001", "--json"])
    err = capsys.readouterr().err
    assert code != 0
    assert "not found" in err.lower() or "invalid" in err.lower()
