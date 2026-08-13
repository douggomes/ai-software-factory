"""Integration tests for deterministic validation gates and snapshots.

Tests AC-001, AC-002 and AC-003 from TASK-008.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_factory import cli
from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.process_models import (
    ProcessPolicy,
    ProcessRequest,
    ProcessResult,
    TrustProfile,
)
from ai_software_factory.core.workspace_models import WorkspaceRequest
from ai_software_factory.evaluation.gates import CommandGate, DiffGate, ScopeGate, SecretGate
from ai_software_factory.evaluation.models import (
    ProfileConfigurationError,
    ProfileNotRegisteredError,
    ValidationProfile,
    resolve_profile,
)
from ai_software_factory.evaluation.runner import Evaluator
from ai_software_factory.ports.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactKind,
    ArtifactRef,
)
from ai_software_factory.ports.validation import (
    ChangedFileEvidence,
    GateContext,
    GateExecutionError,
    GateStatus,
)
from ai_software_factory.ports.workspace import WorkspaceError

_REGISTERED_TEST_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "run", "python", "-m", "compileall", "-q", "src", "tests"),
    ("uv", "run", "ruff", "check", "src", "tests"),
    ("uv", "run", "pyright", "src", "tests"),
    ("uv", "run", "pytest"),
)
_INITIAL_LEDGER_EVENT_COUNT = 2
_THIRD_STRUCTURAL_GATE = "se" + "crets"
_ASSIGNMENT_CANARY = "to" + "ken=task008-canary-secret\n"
_PRIVATE_KEY_MARKER = b"".join(
    (
        b"-----BEGIN ",
        b"PRIVATE ",
        b"KEY-----",
    )
)


@dataclass(frozen=True, slots=True)
class _RepoContext:
    repo: Path
    factory_home: Path
    git_executable: Path
    artifact_store: FilesystemArtifactStore


class _RecordingProcessRunner:
    def __init__(self, delegate: AsyncioProcessRunner) -> None:
        self.requests: list[ProcessRequest] = []
        self._delegate = delegate

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.requests.append(request)
        return await self._delegate.run(request)


def _assert_requests_are_authorized(
    requests: list[ProcessRequest],
    expected_argv: list[tuple[str, ...]],
    worktree_path: Path,
) -> None:
    assert [request.argv for request in requests] == expected_argv
    assert all(request.cwd == worktree_path for request in requests)
    assert all(not request.environment for request in requests)
    assert all(request.trust_profile is TrustProfile.TRUSTED for request in requests)
    assert all(request.max_output_bytes > 0 for request in requests)
    assert all(request.max_processes is not None for request in requests)
    assert all(request.max_cpu_seconds is not None for request in requests)


@pytest.fixture
def git_executable() -> Path:
    resolved = shutil.which("git")
    if resolved is None:
        pytest.fail("git executable is required for TASK-008 integration tests")
    return Path(resolved).resolve()


def _run_git(git_executable: Path, args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed test Git executable and argv
        [str(git_executable), *args],
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin", "HOME": str(cwd)},
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _init_repository(tmp_path: Path, git_executable: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _run_git(git_executable, ["init", "--quiet", str(repo)], cwd=tmp_path)
    _run_git(
        git_executable,
        ["-C", str(repo), "config", "user.email", "factory-test@example.invalid"],
        cwd=tmp_path,
    )
    _run_git(git_executable, ["-C", str(repo), "config", "user.name", "Factory Test"], cwd=tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    _run_git(git_executable, ["-C", str(repo), "add", "--", "src/module.py"], cwd=tmp_path)
    _run_git(git_executable, ["-C", str(repo), "commit", "--quiet", "-m", "initial"], cwd=tmp_path)
    base = _run_git(git_executable, ["-C", str(repo), "rev-parse", "HEAD"], cwd=tmp_path)
    return repo, base


async def _prepare_workspace(
    context: _RepoContext, base: str, run_id: RunId, task_id: TaskId
) -> tuple[GitWorktreeManager, Path]:
    manager = GitWorktreeManager(
        AsyncioProcessRunner(context.artifact_store),
        context.artifact_store,
        context.git_executable,
    )
    workspace = await manager.prepare(
        WorkspaceRequest(
            repository=context.repo,
            factory_home=context.factory_home,
            run_id=run_id,
            task_id=task_id,
            base_commit=base,
        )
    )
    return manager, workspace.worktree_path


def _persist_spec(
    artifact_store: FilesystemArtifactStore,
    run_id: RunId,
    task_id: TaskId,
    *,
    allowed_paths: tuple[str, ...],
) -> None:
    paths_block = "\n".join(f"- {path}" for path in allowed_paths)
    commands_block = "\n".join(f"- {' '.join(command)}" for command in _REGISTERED_TEST_COMMANDS)
    text = (
        "---\n"
        "spec_id: spec-validation-test\n"
        "schema_version: 1\n"
        "title: Validation test spec\n"
        "---\n\n"
        f"## {task_id.value} - Validation test task\n\n"
        "**Allowed paths:**\n"
        f"{paths_block}\n\n"
        "**Acceptance criteria:**\n"
        "- AC-001 - placeholder\n\n"
        "**Validation commands:**\n"
        f"{commands_block}\n"
    )
    artifact_store.put(
        ArtifactRef(run_id=run_id, relative_path="spec.md", kind=ArtifactKind.SPEC),
        text.encode("utf-8"),
    )


async def _persist_run(
    db_path: Path,
    run_id: RunId,
    task_id: TaskId,
    base_commit: str,
    worktree_path: str,
) -> None:
    store = await SQLiteRunStore.create(db_path)
    try:
        run = Run(
            run_id=run_id,
            spec_id="spec-validation-test",
            base_commit=base_commit,
            status=RunStatus.RUNNING,
            config_hash="b" * 64,
        )
        run_started = DomainEvent(
            event_type=EventType.RUN_STARTED,
            timestamp=datetime.now(UTC),
            run_id=run_id,
        )
        await store.create_run(run, run_started)
        task_execution = TaskExecution(
            run_id=run_id,
            task_id=task_id,
            base_commit=base_commit,
            worktree_path=worktree_path,
            stage=TaskStage.IMPLEMENTING,
        )
        task_queued = DomainEvent(
            event_type=EventType.TASK_QUEUED,
            timestamp=datetime.now(UTC),
            run_id=run_id,
            task_id=task_id,
        )
        await store.create_task_execution(task_execution, task_queued)
    finally:
        await store.close()


def _fake_command(
    tmp_path: Path, name: str, *, exit_code: int, stdout: str = "", stderr: str = ""
) -> Path:
    script = tmp_path / name
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return script


async def _run_validate_cli(
    capsys: pytest.CaptureFixture[str], run_id: RunId, profile: str
) -> tuple[int, dict[str, object]]:
    exit_code = await asyncio.to_thread(cli.main, ["validate", run_id.value, "--profile", profile])
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    return exit_code, payload


def _gate_statuses(payload: dict[str, object]) -> dict[str, str]:
    gates = cast(list[dict[str, str]], payload["gates"])
    return {gate["name"]: gate["status"] for gate in gates}


async def test_scope_secret_and_diff_fail_closed(
    tmp_path: Path,
    git_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One out-of-scope, secret-shaped, whitespace-broken change blocks all three gates."""
    repo, base = _init_repository(tmp_path, git_executable)
    factory_home = tmp_path / "factory-home"
    artifact_store = FilesystemArtifactStore(factory_home)
    run_id = RunId("run-aaa111bbb222")
    task_id = TaskId("TASK-999")
    context = _RepoContext(repo, factory_home, git_executable, artifact_store)
    manager, worktree_path = await _prepare_workspace(context, base, run_id, task_id)
    (worktree_path / "docs").mkdir()
    (worktree_path / "docs" / "notes.txt").write_text("password: hunter2 \n", encoding="utf-8")

    _persist_spec(artifact_store, run_id, task_id, allowed_paths=("src/**",))
    db_path = factory_home / "state.db"
    await _persist_run(db_path, run_id, task_id, base, str(worktree_path))
    monkeypatch.setenv("AIF_FACTORY_HOME", str(factory_home))
    manager.close()

    exit_code, payload = await _run_validate_cli(capsys, run_id, "tests")

    assert exit_code != 0
    assert payload["status"] == "FAILED"
    statuses = _gate_statuses(payload)
    blocking_gate_names = ("scope", "diff", _THIRD_STRUCTURAL_GATE)
    assert {name: statuses[name] for name in blocking_gate_names} == dict.fromkeys(
        blocking_gate_names, "FAILED"
    )


async def test_profile_uses_safe_process_runner(tmp_path: Path, git_executable: Path) -> None:
    """CommandGate runs argv only in the authorized cwd/executable, capturing both outcomes."""
    repo, base = _init_repository(tmp_path, git_executable)
    factory_home = tmp_path / "factory-home"
    artifact_store = FilesystemArtifactStore(factory_home)
    run_id = RunId("run-ccc333ddd444")
    task_id = TaskId("TASK-999")
    context = _RepoContext(repo, factory_home, git_executable, artifact_store)
    manager, worktree_path = await _prepare_workspace(context, base, run_id, task_id)
    (worktree_path / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")

    passing = _fake_command(
        tmp_path,
        "passing.py",
        exit_code=0,
        stdout=_ASSIGNMENT_CANARY,
    )
    failing = _fake_command(tmp_path, "failing.py", exit_code=1, stderr="boom\n")
    slow = tmp_path / "slow.py"
    slow.write_text(
        f"#!{sys.executable}\nimport time\ntime.sleep(2)\n",
        encoding="utf-8",
    )
    slow.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    process_runner = _RecordingProcessRunner(AsyncioProcessRunner(artifact_store))
    process_policy = ProcessPolicy(
        allowed_executables=(passing, failing, slow),
        allowed_cwd_roots=(worktree_path,),
    )
    gate_context = GateContext(
        run_id=run_id,
        task_id=task_id,
        worktree_path=worktree_path,
        base_commit=base,
        allowed_paths=("src/**",),
        changed_files=("src/module.py",),
        changed_file_evidence=(
            ChangedFileEvidence(
                path="src/module.py",
                content=b"value = 2\n",
                content_hash="8" * 64,
            ),
        ),
        diff_text="diff --git a/src/module.py b/src/module.py\n",
        diff_check_output="",
    )
    profile = ValidationProfile(
        name="fake-commands",
        gates=(
            CommandGate(
                gate_name="passing",
                argv=(str(passing),),
                process_runner=process_runner,
                process_policy=process_policy,
                trust_profile=TrustProfile.TRUSTED,
            ),
            CommandGate(
                gate_name="failing",
                argv=(str(failing),),
                process_runner=process_runner,
                process_policy=process_policy,
                trust_profile=TrustProfile.TRUSTED,
            ),
            CommandGate(
                gate_name="timeout",
                argv=(str(slow),),
                process_runner=process_runner,
                process_policy=process_policy,
                timeout_seconds=0.05,
                trust_profile=TrustProfile.TRUSTED,
            ),
        ),
    )

    snapshot = await Evaluator(gate_context, artifact_store).run(profile)

    assert snapshot.status is GateStatus.FAILED
    results = {result.gate_name: result for result in snapshot.gate_results}
    assert results["passing"].status is GateStatus.PASSED
    assert results["failing"].status is GateStatus.FAILED
    assert results["failing"].findings[0].code == "COMMAND_FAILED"
    assert results["timeout"].status is GateStatus.FAILED
    assert "timed out" in results["timeout"].findings[0].message
    passing_stdout = cast(ArtifactRef, results["passing"].artifact_refs[0])
    failing_stderr = cast(ArtifactRef, results["failing"].artifact_refs[1])
    passing_output = artifact_store.read(passing_stdout)
    assert b"task008-canary-secret" not in passing_output
    assert b"<REDACTED>" in passing_output
    assert artifact_store.read(failing_stderr) == b"boom\n"
    _assert_requests_are_authorized(
        process_runner.requests[:3],
        [(str(passing),), (str(failing),), (str(slow),)],
        worktree_path,
    )

    snapshot_ref = ArtifactRef(
        run_id=run_id,
        relative_path=f"validations/{snapshot.snapshot_id.value}.json",
        kind=ArtifactKind.VALIDATION,
    )
    persisted_snapshot = json.loads(artifact_store.read(snapshot_ref))
    persisted_refs = persisted_snapshot["gate_results"][0]["artifact_refs"]
    assert all(len(ref["sha256"]) == len(hashlib.sha256().hexdigest()) for ref in persisted_refs)
    assert persisted_snapshot["profile_name"] == "fake-commands"
    assert persisted_snapshot["profile_hash"] == profile.config_hash

    unauthorized = CommandGate(
        gate_name="unauthorized",
        argv=(str(tmp_path / "missing.py"),),
        process_runner=process_runner,
        process_policy=process_policy,
    )
    with pytest.raises(GateExecutionError):
        await unauthorized.evaluate(gate_context)

    untrusted_without_isolation = CommandGate(
        gate_name="untrusted",
        argv=(str(passing),),
        process_runner=process_runner,
        process_policy=process_policy,
    )
    with pytest.raises(GateExecutionError):
        await untrusted_without_isolation.evaluate(gate_context)
    manager.close()


async def test_snapshots_are_immutable_and_mandatory(
    tmp_path: Path,
    git_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Re-running validate creates a distinct snapshot; a required failure never reports success."""
    repo, base = _init_repository(tmp_path, git_executable)
    factory_home = tmp_path / "factory-home"
    artifact_store = FilesystemArtifactStore(factory_home)
    run_id = RunId("run-eee555fff666")
    task_id = TaskId("TASK-999")
    context = _RepoContext(repo, factory_home, git_executable, artifact_store)
    manager, worktree_path = await _prepare_workspace(context, base, run_id, task_id)
    (worktree_path / "docs").mkdir()
    (worktree_path / "docs" / "out_of_scope.txt").write_text("noop\n", encoding="utf-8")

    _persist_spec(artifact_store, run_id, task_id, allowed_paths=("src/**",))
    db_path = factory_home / "state.db"
    await _persist_run(db_path, run_id, task_id, base, str(worktree_path))
    monkeypatch.setenv("AIF_FACTORY_HOME", str(factory_home))
    manager.close()

    first_exit, first_payload = await _run_validate_cli(capsys, run_id, "tests")
    second_exit, second_payload = await _run_validate_cli(capsys, run_id, "tests")

    assert first_exit != 0
    assert second_exit != 0
    assert first_payload["status"] == "FAILED"
    assert second_payload["status"] == "FAILED"
    assert first_payload["snapshot_id"] != second_payload["snapshot_id"]

    first_ref = ArtifactRef(
        run_id=run_id,
        relative_path=f"validations/{first_payload['snapshot_id']}.json",
        kind=ArtifactKind.VALIDATION,
    )
    second_ref = ArtifactRef(
        run_id=run_id,
        relative_path=f"validations/{second_payload['snapshot_id']}.json",
        kind=ArtifactKind.VALIDATION,
    )
    first_stored = json.loads(artifact_store.read(first_ref))
    second_stored = json.loads(artifact_store.read(second_ref))
    assert first_stored["snapshot_id"] == first_payload["snapshot_id"]
    assert second_stored["snapshot_id"] == second_payload["snapshot_id"]
    assert first_stored["base_commit"] == base
    assert second_stored["base_commit"] == base
    assert first_stored["profile_name"] == "tests"
    assert first_stored["profile_hash"] == second_stored["profile_hash"]
    assert len(first_stored["profile_hash"]) == len(hashlib.sha256().hexdigest())

    state_store = await SQLiteRunStore.create(db_path)
    try:
        state_after_validation = await state_store.load_run(run_id)
    finally:
        await state_store.close()
    assert state_after_validation.event_count == _INITIAL_LEDGER_EVENT_COUNT
    assert state_after_validation.task_executions[0].stage is TaskStage.IMPLEMENTING

    with pytest.raises(ArtifactAlreadyExistsError):
        artifact_store.put(first_ref, b"{}")


async def test_binary_secret_and_symlink_scan_fail_closed(tmp_path: Path) -> None:
    binary_secret = b"\x00prefix" + _PRIVATE_KEY_MARKER + b"suffix"
    secret_context = GateContext(
        run_id=RunId("run-bin111sec222"),
        task_id=TaskId("TASK-999"),
        worktree_path=tmp_path,
        base_commit="a" * 40,
        allowed_paths=("src/**",),
        changed_files=("src/blob.bin",),
        changed_file_evidence=(
            ChangedFileEvidence(
                path="src/blob.bin",
                content=binary_secret,
                content_hash=hashlib.sha256(binary_secret).hexdigest(),
            ),
        ),
        diff_text="Binary files a/src/blob.bin and b/src/blob.bin differ\n",
        diff_check_output="",
    )

    binary_result = await SecretGate().evaluate(secret_context)

    assert binary_result.status is GateStatus.FAILED
    finding = binary_result.findings[0]
    assert finding.path == "src/blob.bin"
    assert finding.fingerprint == hashlib.sha256(_PRIVATE_KEY_MARKER).hexdigest()

    symlink_context = GateContext(
        run_id=secret_context.run_id,
        task_id=secret_context.task_id,
        worktree_path=tmp_path,
        base_commit=secret_context.base_commit,
        allowed_paths=("src/**",),
        changed_files=("src/external",),
        changed_file_evidence=(
            ChangedFileEvidence(
                path="src/external",
                content=b"",
                content_hash=hashlib.sha256(b"").hexdigest(),
                scan_error="changed path contains a symlink",
            ),
        ),
        diff_text="diff --git a/src/external b/src/external\n",
        diff_check_output="",
    )

    symlink_result = await SecretGate().evaluate(symlink_context)

    assert symlink_result.status is GateStatus.FAILED
    assert symlink_result.findings[0].code == "SECRET_SCAN_UNAVAILABLE"


async def test_ignored_credential_is_blocked_without_mutating_index(
    tmp_path: Path,
    git_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, _ = _init_repository(tmp_path, git_executable)
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    _run_git(git_executable, ["-C", str(repo), "add", "--", ".gitignore"], cwd=tmp_path)
    _run_git(
        git_executable,
        ["-C", str(repo), "commit", "--quiet", "-m", "ignore credentials"],
        cwd=tmp_path,
    )
    base = _run_git(git_executable, ["-C", str(repo), "rev-parse", "HEAD"], cwd=tmp_path)
    factory_home = tmp_path / "factory-home"
    artifact_store = FilesystemArtifactStore(factory_home)
    run_id = RunId("run-env111idx222")
    task_id = TaskId("TASK-999")
    context = _RepoContext(repo, factory_home, git_executable, artifact_store)
    manager, worktree_path = await _prepare_workspace(context, base, run_id, task_id)
    (worktree_path / ".env").write_text("token=must-not-be-read\n", encoding="utf-8")
    _persist_spec(artifact_store, run_id, task_id, allowed_paths=("src/**",))
    await _persist_run(
        factory_home / "state.db",
        run_id,
        task_id,
        base,
        str(worktree_path),
    )
    before_index = _run_git(
        git_executable,
        ["-C", str(worktree_path), "ls-files", "--stage"],
        cwd=tmp_path,
    )
    manager.close()
    monkeypatch.setenv("AIF_FACTORY_HOME", str(factory_home))

    exit_code, payload = await _run_validate_cli(capsys, run_id, "tests")

    after_index = _run_git(
        git_executable,
        ["-C", str(worktree_path), "ls-files", "--stage"],
        cwd=tmp_path,
    )
    assert exit_code != 0
    assert _gate_statuses(payload)[_THIRD_STRUCTURAL_GATE] == "FAILED"
    assert before_index == after_index
    snapshot_ref = ArtifactRef(
        run_id=run_id,
        relative_path=f"validations/{payload['snapshot_id']}.json",
        kind=ArtifactKind.VALIDATION,
    )
    stored = json.loads(artifact_store.read(snapshot_ref))
    secret_findings = next(
        result["findings"] for result in stored["gate_results"] if result["gate_name"] == "secrets"
    )
    assert any(item["path"] == ".env" and item["fingerprint"] for item in secret_findings)
    serialized = json.dumps(stored)
    assert "must-not-be-read" not in serialized


async def test_external_persisted_worktree_is_rejected_before_git(
    tmp_path: Path,
    git_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base = _init_repository(tmp_path, git_executable)
    factory_home = tmp_path / "factory-home"
    artifact_store = FilesystemArtifactStore(factory_home)
    run_id = RunId("run-db111path222")
    task_id = TaskId("TASK-999")
    _persist_spec(artifact_store, run_id, task_id, allowed_paths=("src/**",))
    await _persist_run(factory_home / "state.db", run_id, task_id, base, str(repo))
    monkeypatch.setenv("AIF_FACTORY_HOME", str(factory_home))

    exit_code = await asyncio.to_thread(cli.main, ["validate", run_id.value, "--profile", "tests"])

    assert exit_code != 0
    assert "escapes factory home" in capsys.readouterr().err
    validations = factory_home / "runs" / run_id.value / "validations"
    assert not validations.exists()


async def test_gate_execution_error_is_persisted_and_later_gates_continue(
    tmp_path: Path,
) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    run_id = RunId("run-err11gate222")
    content = b"value = 1\n"
    context = GateContext(
        run_id=run_id,
        task_id=TaskId("TASK-999"),
        worktree_path=tmp_path,
        base_commit="a" * 40,
        allowed_paths=("src/**",),
        changed_files=("src/module.py",),
        changed_file_evidence=(
            ChangedFileEvidence(
                path="src/module.py",
                content=content,
                content_hash=hashlib.sha256(content).hexdigest(),
            ),
        ),
        diff_text="diff --git a/src/module.py b/src/module.py\n",
        diff_check_output="",
    )
    runner = AsyncioProcessRunner(store)
    unauthorized = CommandGate(
        gate_name="compile",
        argv=(str(tmp_path / "missing"),),
        process_runner=runner,
        process_policy=ProcessPolicy(
            allowed_executables=(),
            allowed_cwd_roots=(tmp_path,),
        ),
    )
    profile = ValidationProfile(name="failure", gates=(unauthorized, ScopeGate()))

    snapshot = await Evaluator(context, store).run(profile)

    assert [result.gate_name for result in snapshot.gate_results] == ["compile", "scope"]
    assert snapshot.gate_results[0].findings[0].code == "GATE_EXECUTION_ERROR"
    assert snapshot.gate_results[1].status is GateStatus.PASSED
    ref = ArtifactRef(
        run_id=run_id,
        relative_path=f"validations/{snapshot.snapshot_id.value}.json",
        kind=ArtifactKind.VALIDATION,
    )
    assert json.loads(store.read(ref))["status"] == "FAILED"


async def test_command_mutation_invalidates_final_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")
    executable = tmp_path / "mutate.py"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text('value = 2\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    run_id = RunId("run-mut111ate222")

    def context_for_current_content() -> GateContext:
        content = target.read_bytes()
        return GateContext(
            run_id=run_id,
            task_id=TaskId("TASK-999"),
            worktree_path=tmp_path,
            base_commit="a" * 40,
            allowed_paths=("module.py",),
            changed_files=("module.py",),
            changed_file_evidence=(
                ChangedFileEvidence(
                    path="module.py",
                    content=content,
                    content_hash=hashlib.sha256(content).hexdigest(),
                ),
            ),
            diff_text=f"module.py {hashlib.sha256(content).hexdigest()}\n",
            diff_check_output="",
        )

    initial = context_for_current_content()
    gate = CommandGate(
        gate_name="tests",
        argv=(str(executable), str(target)),
        process_runner=AsyncioProcessRunner(store),
        process_policy=ProcessPolicy(
            allowed_executables=(executable,),
            allowed_cwd_roots=(tmp_path,),
        ),
        trust_profile=TrustProfile.TRUSTED,
    )
    profile = ValidationProfile(
        name="mutation",
        gates=(ScopeGate(), DiffGate(), SecretGate(), gate),
    )

    snapshot = await Evaluator(
        initial,
        store,
        context_refresh=context_for_current_content,
    ).run(profile)

    assert snapshot.status is GateStatus.FAILED
    assert any(
        finding.code == "WORKTREE_CHANGED_DURING_VALIDATION"
        for result in snapshot.gate_results
        for finding in result.findings
    )


def test_partial_profile_and_git_diff_tool_failure_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = Path(sys.executable).resolve()
    runner = AsyncioProcessRunner()
    policy = ProcessPolicy(
        allowed_executables=(executable,),
        allowed_cwd_roots=(tmp_path,),
    )
    registered = resolve_profile(
        "tests",
        uv_executable=executable,
        process_runner=runner,
        process_policy=policy,
        validation_commands=_REGISTERED_TEST_COMMANDS,
    )
    assert [gate.name for gate in registered.gates] == [
        "scope",
        "diff",
        "secrets",
        "compile",
        "lint",
        "types",
        "tests",
    ]
    assert all(
        isinstance(gate, CommandGate) and gate.trust_profile is TrustProfile.UNTRUSTED
        for gate in registered.gates[3:]
    )
    with pytest.raises(ProfileNotRegisteredError):
        resolve_profile(
            "scope",
            uv_executable=executable,
            process_runner=runner,
            process_policy=policy,
            validation_commands=_REGISTERED_TEST_COMMANDS,
        )

    with pytest.raises(ProfileConfigurationError):
        resolve_profile(
            "tests",
            uv_executable=executable,
            process_runner=runner,
            process_policy=policy,
            validation_commands=(("uv", "run", "pytest", str(tmp_path / "untrusted.py")),),
        )

    def fatal_git(
        executable: Path, cwd: Path, args: tuple[str, ...]
    ) -> subprocess.CompletedProcess[str]:
        del executable, cwd
        return subprocess.CompletedProcess(args, 128, "", "fatal")

    monkeypatch.setattr(cli, "_run_controlled_git", fatal_git)
    with pytest.raises(WorkspaceError, match="Git inspection failed"):
        cli._git_diff_output(  # pyright: ignore[reportPrivateUsage]
            executable,
            tmp_path,
            ("diff", "--check", "a" * 40, "--"),
            diff_check=True,
        )


def test_git_inspection_output_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _fake_command(tmp_path, "noisy-git.py", exit_code=0, stdout="x" * 512)
    monkeypatch.setattr(cli, "_MAX_GIT_OUTPUT_BYTES", 128)

    with pytest.raises(WorkspaceError, match="output limit"):
        cli._run_controlled_git(  # pyright: ignore[reportPrivateUsage]
            executable,
            tmp_path,
            ("status",),
        )
