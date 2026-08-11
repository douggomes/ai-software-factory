"""Integration tests for SQLiteRunStore.

Tests AC-001, AC-002 and AC-003 from TASK-004.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import textwrap
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, text
from sqlalchemy import select as sa_select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from ai_software_factory.adapters.persistence import sqlite as sqlite_module
from ai_software_factory.adapters.persistence.schema import (
    runs_table,
    schema_version_table,
    task_executions_table,
)
from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore
from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.state_machine import Transition
from ai_software_factory.ports.persistence import OptimisticLockError, SchemaVersionError


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SQLiteRunStore]:
    db_path = tmp_path / "test.db"
    store = await SQLiteRunStore.create(db_path)
    try:
        yield store
    finally:
        await store.close()


def _make_run(run_id: str = "run-abc123def456") -> Run:
    return Run(
        run_id=RunId(run_id),
        spec_id="spec-001",
        base_commit="a" * 40,
        status=RunStatus.QUEUED,
        config_hash="b" * 64,
    )


def _make_event(run_id: str = "run-abc123def456") -> DomainEvent:
    return DomainEvent(
        event_type=EventType.RUN_STARTED,
        timestamp=datetime.now(UTC),
        run_id=RunId(run_id),
    )


def _make_task_execution(
    run_id: str = "run-abc123def456", task_id: str = "TASK-001"
) -> TaskExecution:
    return TaskExecution(
        run_id=RunId(run_id),
        task_id=TaskId(task_id),
        base_commit="a" * 40,
        worktree_path="/worktrees/test",
        stage=TaskStage.QUEUED,
    )


async def test_persists_across_reopen(tmp_path: Path) -> None:
    """AC-001: Run created can be loaded after closing and reopening the store."""
    db_path = tmp_path / "test.db"
    store1 = await SQLiteRunStore.create(db_path)
    run = _make_run()
    event = _make_event()
    await store1.create_run(run, event)
    await store1.close()
    store2 = await SQLiteRunStore.create(db_path)
    snapshot = await store2.load_run(run.run_id)
    assert snapshot.run.run_id == run.run_id
    assert snapshot.run.spec_id == run.spec_id
    assert snapshot.run.base_commit == run.base_commit
    assert snapshot.run.status == run.status
    assert snapshot.run.config_hash == run.config_hash
    assert snapshot.event_count == 1
    await store2.close()


async def test_event_failure_rolls_back_transition(store: SQLiteRunStore) -> None:
    """AC-002: Event write failure rolls back the entire transition."""
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    te = _make_task_execution()
    te_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    await store.create_task_execution(te, te_event)
    snapshot_before = await store.load_run(run.run_id)
    event_count_before = snapshot_before.event_count
    transition_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    wrong_transition = Transition(
        from_stage=TaskStage.IMPLEMENTING,
        to_stage=TaskStage.DETERMINISTIC_VALIDATION,
        event=transition_event,
    )
    with pytest.raises(OptimisticLockError):
        await store.transition(run.run_id, te.task_id, wrong_transition)
    loaded = await store.load_task_execution(run.run_id, te.task_id)
    assert loaded.stage == TaskStage.QUEUED
    snapshot_after = await store.load_run(run.run_id)
    assert snapshot_after.event_count == event_count_before


async def test_concurrent_sessions(tmp_path: Path) -> None:
    """AC-003: Concurrent sessions can read and write without corruption."""
    db_path = tmp_path / "test.db"
    store1 = await SQLiteRunStore.create(db_path)
    store2 = await SQLiteRunStore.create(db_path)
    run1 = _make_run("run-aaa111bbb222")
    event1 = _make_event("run-aaa111bbb222")
    run2 = _make_run("run-ccc333ddd444")
    event2 = _make_event("run-ccc333ddd444")
    await store1.create_run(run1, event1)
    await store2.create_run(run2, event2)
    snapshot1 = await store2.load_run(run1.run_id)
    snapshot2 = await store1.load_run(run2.run_id)
    assert snapshot1.run.run_id == run1.run_id
    assert snapshot2.run.run_id == run2.run_id
    await store1.close()
    await store2.close()


async def test_schema_version_recorded(store: SQLiteRunStore) -> None:
    """Verify schema version is recorded during initialization."""
    async with store._engine.connect() as conn:  # pyright: ignore[reportPrivateUsage]
        result = await conn.execute(
            sa_select(schema_version_table.c.version).order_by(schema_version_table.c.version)
        )
        assert list(result.scalars()) == [1, 2]


async def test_multiple_task_executions(store: SQLiteRunStore) -> None:
    """Verify multiple task executions can be created for the same run."""
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    te1 = _make_task_execution(task_id="TASK-001")
    te2 = _make_task_execution(task_id="TASK-002")
    te1_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te1.task_id,
    )
    te2_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te2.task_id,
    )
    await store.create_task_execution(te1, te1_event)
    await store.create_task_execution(te2, te2_event)
    snapshot = await store.load_run(run.run_id)
    expected_task_count = 2
    assert len(snapshot.task_executions) == expected_task_count
    task_ids = {te.task_id.value for te in snapshot.task_executions}
    assert task_ids == {"TASK-001", "TASK-002"}


async def test_transition_sequence(store: SQLiteRunStore) -> None:
    """Verify a sequence of transitions works correctly."""
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    te = _make_task_execution()
    te_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    await store.create_task_execution(te, te_event)
    transition1_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    transition1 = Transition(
        from_stage=TaskStage.QUEUED,
        to_stage=TaskStage.PREFLIGHT,
        event=transition1_event,
    )
    await store.transition(run.run_id, te.task_id, transition1)
    transition2_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    transition2 = Transition(
        from_stage=TaskStage.PREFLIGHT,
        to_stage=TaskStage.WORKSPACE_PREPARING,
        event=transition2_event,
    )
    await store.transition(run.run_id, te.task_id, transition2)
    loaded = await store.load_task_execution(run.run_id, te.task_id)
    assert loaded.stage == TaskStage.WORKSPACE_PREPARING


async def test_foreign_keys_enabled_on_every_pooled_connection(store: SQLiteRunStore) -> None:
    """QA-004-002 regression: every pooled connection enforces foreign keys, not just the first."""
    async with store._engine.connect() as conn1:  # pyright: ignore[reportPrivateUsage]
        first = (await conn1.execute(text("PRAGMA foreign_keys"))).scalar_one()
        async with store._engine.connect() as conn2:  # pyright: ignore[reportPrivateUsage]
            second = (await conn2.execute(text("PRAGMA foreign_keys"))).scalar_one()
    assert first == 1
    assert second == 1


async def test_runtime_directory_and_database_have_restrictive_permissions(
    tmp_path: Path,
) -> None:
    """QA-004-004 regression: runtime dir is 0700 and DB file is 0600 regardless of umask."""
    expected_dir_mode = 0o700
    expected_db_mode = 0o600
    permissive_umask = 0o022
    original_umask = os.umask(permissive_umask)
    try:
        db_path = tmp_path / "runtime" / "test.db"
        store = await SQLiteRunStore.create(db_path)
        try:
            dir_mode = stat.S_IMODE(db_path.parent.stat().st_mode)
            db_mode = stat.S_IMODE(db_path.stat().st_mode)
            assert dir_mode == expected_dir_mode
            assert db_mode == expected_db_mode
        finally:
            await store.close()
    finally:
        os.umask(original_umask)


async def test_future_schema_version_is_rejected(tmp_path: Path) -> None:
    """QA-004-005 regression: a schema version newer than supported fails closed."""
    db_path = tmp_path / "future.db"
    seed_store = await SQLiteRunStore.create(db_path)
    await seed_store.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                schema_version_table.insert().values(version=999, applied_at=datetime.now(UTC))
            )
    finally:
        await engine.dispose()

    with pytest.raises(SchemaVersionError):
        await SQLiteRunStore.create(db_path)


async def test_database_rejects_base_commit_of_wrong_length(store: SQLiteRunStore) -> None:
    """QA-004-006 regression: DB CHECK constraints back domain validation, not just create_all."""
    with pytest.raises(IntegrityError):
        async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
            await conn.execute(
                insert(runs_table).values(
                    run_id="run-zzzzzzzzzzzz",
                    spec_id="spec-1",
                    base_commit="short",
                    status="QUEUED",
                    config_hash="b" * 64,
                )
            )


async def test_database_rejects_unknown_status_enum_value(store: SQLiteRunStore) -> None:
    """QA-004-006 regression: status is constrained to the domain's RunStatus enum values."""
    with pytest.raises(IntegrityError):
        async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
            await conn.execute(
                insert(runs_table).values(
                    run_id="run-yyyyyyyyyyyy",
                    spec_id="spec-1",
                    base_commit="a" * 40,
                    status="NOT_A_REAL_STATUS",
                    config_hash="b" * 64,
                )
            )


async def test_database_rejects_invalid_run_id_characters(store: SQLiteRunStore) -> None:
    """Database constraints mirror the RunId lowercase-alphanumeric suffix."""
    with pytest.raises(IntegrityError):
        async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
            await conn.execute(
                insert(runs_table).values(
                    run_id="run-!!!!!!!!!!!!",
                    spec_id="spec-1",
                    base_commit="a" * 40,
                    status="QUEUED",
                    config_hash="b" * 64,
                )
            )


@pytest.mark.parametrize(
    ("base_commit", "config_hash"),
    [("g" * 40, "b" * 64), ("a" * 40, "!" * 64)],
)
async def test_database_rejects_non_hex_hashes(
    store: SQLiteRunStore, base_commit: str, config_hash: str
) -> None:
    """Length alone is insufficient: commit and config hashes must be lowercase hex."""
    with pytest.raises(IntegrityError):
        async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
            await conn.execute(
                insert(runs_table).values(
                    run_id="run-hexcheck0001",
                    spec_id="spec-1",
                    base_commit=base_commit,
                    status="QUEUED",
                    config_hash=config_hash,
                )
            )


async def test_database_rejects_non_numeric_task_id(store: SQLiteRunStore, tmp_path: Path) -> None:
    """TaskId database constraints require digits after the TASK- prefix."""
    run = _make_run()
    await store.create_run(run, _make_event())
    with pytest.raises(IntegrityError):
        async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
            await conn.execute(
                insert(task_executions_table).values(
                    run_id=run.run_id.value,
                    task_id="TASK-ABC",
                    base_commit="a" * 40,
                    worktree_path=str(tmp_path / "qa-worktree"),
                    stage="QUEUED",
                    repair_count=0,
                    failover_count=0,
                    version=1,
                )
            )


def _create_legacy_v1_database(db_path: Path, worktree: Path, config_hash: str) -> None:
    root = Path(__file__).resolve().parents[2]
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            (root / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
        )
        connection.execute(
            "INSERT INTO runs(run_id, spec_id, base_commit, status, config_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            ("run-legacy000001", "spec-legacy", "a" * 40, "QUEUED", config_hash),
        )
        connection.execute(
            "INSERT INTO task_executions("
            "run_id, task_id, base_commit, worktree_path, stage, "
            "repair_count, failover_count, version"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-legacy000001",
                "TASK-001",
                "a" * 40,
                str(worktree),
                "QUEUED",
                0,
                0,
                1,
            ),
        )
        connection.execute(
            "INSERT INTO events(event_type, timestamp, run_id, task_id, schema_version) "
            "VALUES (?, datetime('now'), ?, ?, ?)",
            ("TASK_QUEUED", "run-legacy000001", "TASK-001", 1),
        )
        connection.commit()
    finally:
        connection.close()


async def test_upgrades_legacy_v1_database_and_preserves_data(tmp_path: Path) -> None:
    """A database created by the previously released V1 migration is upgraded to V2."""
    db_path = tmp_path / "legacy-v1.db"
    _create_legacy_v1_database(db_path, tmp_path / "legacy-worktree", "b" * 64)

    store = await SQLiteRunStore.create(db_path)
    try:
        snapshot = await store.load_run(RunId("run-legacy000001"))
        assert snapshot.run.spec_id == "spec-legacy"
        assert len(snapshot.task_executions) == 1
        assert snapshot.task_executions[0].task_id == TaskId("TASK-001")
        assert snapshot.event_count == 1
        async with store._engine.connect() as conn:  # pyright: ignore[reportPrivateUsage]
            versions = await conn.execute(
                sa_select(schema_version_table.c.version).order_by(schema_version_table.c.version)
            )
            assert list(versions.scalars()) == [1, 2]
        with pytest.raises(IntegrityError):
            async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
                await conn.execute(
                    insert(runs_table).values(
                        run_id="run-valid0000001",
                        spec_id="spec-invalid",
                        base_commit="a" * 40,
                        status="QUEUED",
                        config_hash="tiny",
                    )
                )
    finally:
        await store.close()


async def test_invalid_legacy_v1_upgrade_rolls_back_atomically(tmp_path: Path) -> None:
    """Invalid legacy data aborts V2 without leaving renamed or partially copied tables."""
    db_path = tmp_path / "invalid-legacy-v1.db"
    _create_legacy_v1_database(db_path, tmp_path / "legacy-worktree", "tiny")

    with pytest.raises(IntegrityError):
        await SQLiteRunStore.create(db_path)

    connection = sqlite3.connect(db_path)
    try:
        version = connection.execute("SELECT max(version) FROM schema_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        persisted_hash = connection.execute(
            "SELECT config_hash FROM runs WHERE run_id = 'run-legacy000001'"
        ).fetchone()
    finally:
        connection.close()

    assert version == (1,)
    assert not any(name.endswith("_v1") for name in tables)
    assert persisted_hash == ("tiny",)


def test_built_wheel_contains_migrations_and_initializes_store(tmp_path: Path) -> None:
    """The installable wheel carries migrations and can create a fresh SQLite store."""
    root = Path(__file__).resolve().parents[2]
    uv_executable = shutil.which("uv")
    assert uv_executable is not None
    wheel_dir = tmp_path / "wheel"
    subprocess.run(  # noqa: S603 - fixed build command in a controlled checkout
        [uv_executable, "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    wheels = tuple(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "ai_software_factory/migrations/0001_initial.sql" in names
    assert "ai_software_factory/migrations/0002_harden_constraints.sql" in names

    smoke = textwrap.dedent(
        """
        import asyncio
        import sys
        from pathlib import Path

        sys.path.insert(0, sys.argv[1])
        from ai_software_factory.adapters.persistence import sqlite as sqlite_module
        from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore

        async def main():
            assert '.whl/' in str(sqlite_module.__file__)
            store = await SQLiteRunStore.create(Path(sys.argv[2]))
            await store.close()

        asyncio.run(main())
        """
    )
    subprocess.run(  # noqa: S603 - current interpreter runs a fixed local smoke script
        [sys.executable, "-c", smoke, str(wheel), str(tmp_path / "runtime" / "state.db")],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_load_migrations_skips_non_matching_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "0001_initial.sql").write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    (tmp_path / "not_a_migration.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(sqlite_module, "_MIGRATIONS_ROOT", tmp_path)

    migrations = sqlite_module._load_migrations()  # pyright: ignore[reportPrivateUsage]

    assert [version for version, _ in migrations] == [1]


async def test_missing_migrations_raise_schema_version_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-004-005: with no migration to apply, the store fails closed instead of no-op."""
    empty_migrations_dir = tmp_path / "empty-migrations"
    empty_migrations_dir.mkdir()
    monkeypatch.setattr(sqlite_module, "_MIGRATIONS_ROOT", empty_migrations_dir)

    with pytest.raises(SchemaVersionError):
        await SQLiteRunStore.create(tmp_path / "orphan.db")


def test_statements_skips_empty_segments_between_semicolons() -> None:
    sql = "SELECT 1;;  -- trailing comment, no further statement\n"

    assert sqlite_module._statements(sql) == ["SELECT 1"]  # pyright: ignore[reportPrivateUsage]


def test_statements_includes_final_statement_without_trailing_semicolon() -> None:
    sql = "SELECT 1"

    assert sqlite_module._statements(sql) == ["SELECT 1"]  # pyright: ignore[reportPrivateUsage]
