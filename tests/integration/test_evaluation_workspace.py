"""Integration tests for private evaluation snapshots and Git evidence."""

from __future__ import annotations

import fcntl
import os
import shutil
import stat
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final, cast

import pytest

from ai_software_factory.adapters.git import evaluation_workspace as evaluation_module
from ai_software_factory.adapters.git.evaluation_workspace import GitEvaluationWorkspace
from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.core.evaluation_workspace import EvaluationCaptureRequest
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.workspace_models import Workspace, WorkspaceRequest
from ai_software_factory.ports.artifacts import ArtifactError, ArtifactRef, StoredArtifact
from ai_software_factory.ports.evaluation_workspace import (
    EvaluationWorkspaceArtifactError,
    EvaluationWorkspaceChangedError,
)

_GIT_USER_EMAIL: Final[str] = "evaluation@example.invalid"
_GIT_USER_NAME: Final[str] = "Evaluation Test"


@pytest.fixture
def git_executable() -> Path:
    executable = shutil.which("git")
    if executable is None:
        pytest.fail("git is required for evaluation workspace integration tests")
    return Path(executable).resolve()


@pytest.fixture
async def evaluation_context(
    tmp_path: Path,
    git_executable: Path,
) -> AsyncIterator[tuple[Workspace, GitWorktreeManager, FilesystemArtifactStore, Path]]:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(git_executable, repository, "init", "--quiet")
    _git(git_executable, repository, "config", "user.email", _GIT_USER_EMAIL)
    _git(git_executable, repository, "config", "user.name", _GIT_USER_NAME)
    (repository / ".gitignore").write_text("cache.bin\n.npmrc\n", encoding="utf-8")
    (repository / "README.md").write_text("initial\n", encoding="utf-8")
    _git(git_executable, repository, "add", "--", ".gitignore", "README.md")
    _git(git_executable, repository, "commit", "--quiet", "-m", "initial")
    base = _git(git_executable, repository, "rev-parse", "HEAD")
    factory_home = tmp_path / "factory-home"
    store = FilesystemArtifactStore(factory_home)
    runner = AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer)
    manager = GitWorktreeManager(runner, store, git_executable)
    workspace = await manager.prepare(
        WorkspaceRequest(
            repository=repository,
            factory_home=factory_home,
            run_id=RunId("run-abc123def456"),
            task_id=TaskId("TASK-035"),
            base_commit=base,
        )
    )
    yield workspace, manager, store, git_executable
    manager.close()


@pytest.mark.asyncio
async def test_inventory_covers_ignored_binary_and_secret_evidence(
    evaluation_context: tuple[Workspace, GitWorktreeManager, FilesystemArtifactStore, Path],
) -> None:
    workspace, manager, store, git_executable = evaluation_context
    process_artifacts_before = set(store.root.rglob("*.bin"))
    (workspace.repository / ".git" / "info" / "exclude").write_text(
        "local.secret\n",
        encoding="utf-8",
    )
    (workspace.worktree_path / "README.md").write_text("changed\n", encoding="utf-8")
    (workspace.worktree_path / "notes.txt").write_text("untracked\n", encoding="utf-8")
    (workspace.worktree_path / "cache.bin").write_bytes(b"binary\x00payload")
    (workspace.worktree_path / "local.secret").write_text(
        "token=repository-local-secret\n",
        encoding="utf-8",
    )
    boundary_value = "boundary-secret-value"
    (workspace.worktree_path / "wide.json").write_text(
        '{"token":' + (" " * 70_000) + f'"{boundary_value}"}}\n',
        encoding="utf-8",
    )
    credential_value = "registry-" + "credential-value"
    (workspace.worktree_path / ".npmrc").write_text(
        "token=" + credential_value + "\n",
        encoding="utf-8",
    )
    adapter = GitEvaluationWorkspace(
        AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer),
        store,
        git_executable,
        manager,
        snapshot_id_factory=lambda: "snap-111111111111",
    )

    snapshot = await adapter.capture(EvaluationCaptureRequest(workspace))

    assert "README.md" in snapshot.evidence.tracked_paths
    assert snapshot.evidence.untracked_paths == ("notes.txt", "wide.json")
    assert snapshot.evidence.ignored_paths == (".npmrc", "cache.bin", "local.secret")
    assert snapshot.evidence.binary_paths == ("cache.bin",)
    assert set(snapshot.evidence.changed_paths) == {
        ".npmrc",
        "README.md",
        "cache.bin",
        "local.secret",
        "notes.txt",
        "wide.json",
    }
    findings = {(item.kind, item.path) for item in snapshot.evidence.secret_findings}
    assert ("credential-path", ".npmrc") in findings
    assert ("credential-assignment", ".npmrc") in findings
    assert ("credential-assignment", "local.secret") in findings
    assert ("credential-assignment", "wide.json") in findings
    assert not (snapshot.root / "local.secret").exists()
    assert not (snapshot.root / ".npmrc").exists()
    assert not (snapshot.root / "wide.json").exists()
    assert (snapshot.root / "cache.bin").read_bytes() == b"binary\x00payload"
    manifest = store.read(cast(ArtifactRef, snapshot.manifest_ref))
    assert credential_value.encode() not in manifest
    assert boundary_value.encode() not in manifest
    assert str(workspace.worktree_path).encode() not in manifest
    assert adapter.inspect(snapshot) == snapshot.evidence
    new_process_artifacts = set(store.root.rglob("*.bin")) - process_artifacts_before
    assert new_process_artifacts
    for artifact_path in new_process_artifacts:
        assert str(workspace.worktree_path).encode() not in artifact_path.read_bytes()


@pytest.mark.asyncio
async def test_snapshot_identity_hash_and_toctou(
    evaluation_context: tuple[Workspace, GitWorktreeManager, FilesystemArtifactStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, manager, store, git_executable = evaluation_context
    source = workspace.worktree_path / "README.md"
    source.write_text("stable change\n", encoding="utf-8")
    original_verify = evaluation_module._verify_source  # pyright: ignore[reportPrivateUsage]

    def concurrent_writer(root: int, entries: object) -> None:
        source.write_text("concurrent change\n", encoding="utf-8")
        original_verify(root, cast(tuple[evaluation_module.ManifestEntry, ...], entries))

    monkeypatch.setattr(evaluation_module, "_verify_source", concurrent_writer)
    failing = GitEvaluationWorkspace(
        AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer),
        store,
        git_executable,
        manager,
        snapshot_id_factory=lambda: "snap-222222222222",
    )
    with pytest.raises(EvaluationWorkspaceChangedError):
        await failing.capture(EvaluationCaptureRequest(workspace))

    monkeypatch.setattr(evaluation_module, "_verify_source", original_verify)
    source.write_text("stable change\n", encoding="utf-8")
    successful = GitEvaluationWorkspace(
        AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer),
        store,
        git_executable,
        manager,
        snapshot_id_factory=lambda: "snap-333333333333",
    )
    before = source.read_bytes()
    snapshot = await successful.capture(EvaluationCaptureRequest(workspace))
    assert source.read_bytes() == before
    copied = snapshot.root / "README.md"
    copied.chmod(stat.S_IRUSR | stat.S_IWUSR)
    copied.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(EvaluationWorkspaceArtifactError):
        successful.inspect(snapshot)

    manager.close()
    stale_lock = GitEvaluationWorkspace(
        AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer),
        store,
        git_executable,
        manager,
        snapshot_id_factory=lambda: "snap-444444444444",
    )
    with pytest.raises(evaluation_module.EvaluationWorkspacePolicyError):
        await stale_lock.capture(EvaluationCaptureRequest(workspace))


@pytest.mark.asyncio
async def test_manager_close_invalidates_lease_without_unlocking_mid_capture(
    evaluation_context: tuple[Workspace, GitWorktreeManager, FilesystemArtifactStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, manager, store, git_executable = evaluation_context
    original_verify = evaluation_module._verify_source  # pyright: ignore[reportPrivateUsage]
    released = False

    def release_during_capture(root_fd: int, entries: object) -> None:
        nonlocal released
        original_verify(root_fd, cast(tuple[evaluation_module.ManifestEntry, ...], entries))
        if not released:
            manager.close()
            replacement_fd = os.open(workspace.lock_path, os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(replacement_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(replacement_fd)
            released = True

    monkeypatch.setattr(evaluation_module, "_verify_source", release_during_capture)
    adapter = GitEvaluationWorkspace(
        AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer),
        store,
        git_executable,
        manager,
        snapshot_id_factory=lambda: "snap-888888888888",
    )

    with pytest.raises(EvaluationWorkspaceChangedError):
        await adapter.capture(EvaluationCaptureRequest(workspace))

    replacement_fd = os.open(workspace.lock_path, os.O_RDWR)
    try:
        fcntl.flock(replacement_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        fcntl.flock(replacement_fd, fcntl.LOCK_UN)
        os.close(replacement_fd)

    assert not (
        workspace.factory_home
        / "evaluations"
        / evaluation_module._evaluation_repository_id(  # pyright: ignore[reportPrivateUsage]
            workspace.repository
        )
        / workspace.run_id.value
        / workspace.task_id.value
        / "snap-888888888888"
    ).exists()


@pytest.mark.asyncio
async def test_limits_special_files_and_failed_publication_are_recoverable(
    evaluation_context: tuple[Workspace, GitWorktreeManager, FilesystemArtifactStore, Path],
) -> None:
    workspace, manager, store, git_executable = evaluation_context
    oversized = workspace.worktree_path / "oversized.bin"
    with oversized.open("wb") as stream:
        stream.truncate(1024)
    limited = GitEvaluationWorkspace(
        AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer),
        store,
        git_executable,
        manager,
        snapshot_id_factory=lambda: "snap-555555555555",
    )
    with pytest.raises(evaluation_module.EvaluationWorkspacePolicyError):
        await limited.capture(EvaluationCaptureRequest(workspace, max_total_bytes=16))

    oversized.unlink()
    linked = workspace.worktree_path / "linked.txt"
    os.link(workspace.worktree_path / "README.md", linked)
    with pytest.raises(evaluation_module.EvaluationWorkspacePolicyError):
        await limited.capture(EvaluationCaptureRequest(workspace))
    linked.unlink()

    fifo = workspace.worktree_path / "blocked.pipe"
    fifo_path = str(fifo)
    os.mkfifo(fifo_path)
    root_fd = evaluation_module._open_directory(  # pyright: ignore[reportPrivateUsage]
        workspace.worktree_path
    )
    try:
        with pytest.raises(evaluation_module.EvaluationWorkspacePolicyError):
            evaluation_module._scan_source_file(  # pyright: ignore[reportPrivateUsage]
                root_fd, "blocked.pipe", 1024
            )
    finally:
        os.close(root_fd)
    fifo.unlink()

    class FailManifestStore:
        def put(self, ref: ArtifactRef, data: bytes) -> StoredArtifact:
            if ref.relative_path.startswith("evaluations/"):
                raise ArtifactError("injected manifest failure")
            return store.put(ref, data)

        def read(self, ref: ArtifactRef) -> bytes:
            return store.read(ref)

    failing_store = FailManifestStore()
    snapshot_id = "snap-666666666666"
    failing = GitEvaluationWorkspace(
        AsyncioProcessRunner(failing_store, sanitizer_factory=StreamingOutputSanitizer),
        failing_store,
        git_executable,
        manager,
        snapshot_id_factory=lambda: snapshot_id,
    )
    with pytest.raises(EvaluationWorkspaceArtifactError):
        await failing.capture(EvaluationCaptureRequest(workspace))
    expected = (
        workspace.factory_home
        / "evaluations"
        / evaluation_module._evaluation_repository_id(  # pyright: ignore[reportPrivateUsage]
            workspace.repository
        )
        / workspace.run_id.value
        / workspace.task_id.value
        / snapshot_id
    )
    assert not expected.exists()


def _git(executable: Path, cwd: Path, *arguments: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed Git executable in an isolated fixture
        [str(executable), "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin", "HOME": str(cwd)},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()
