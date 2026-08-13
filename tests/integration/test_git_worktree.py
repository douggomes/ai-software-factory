"""Integration tests for isolated Git workspaces."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Final

import pytest

from ai_software_factory import cli
from ai_software_factory.adapters.git import worktrees as worktrees_module
from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.workspace_models import WorkspaceRequest
from ai_software_factory.ports.workspace import (
    WorkspaceIdentityError,
    WorkspaceLockError,
    WorkspacePolicyError,
)

_GIT_USER_EMAIL: Final[str] = "factory-test@example.invalid"
_GIT_USER_NAME: Final[str] = "Factory Test"


@pytest.fixture
def git_executable() -> Path:
    resolved = shutil.which("git")
    if resolved is None:
        pytest.fail("git executable is required for TASK-007 integration tests")
    return Path(resolved).resolve()


@pytest.fixture
def repository(tmp_path: Path, git_executable: Path) -> tuple[Path, str, Path]:
    repo = tmp_path / "repo"
    canary = tmp_path / "hook-canary"
    _run_git(git_executable, ["init", "--quiet", str(repo)], cwd=tmp_path)
    _run_git(
        git_executable,
        ["-C", str(repo), "config", "user.email", _GIT_USER_EMAIL],
        cwd=tmp_path,
    )
    _run_git(
        git_executable,
        ["-C", str(repo), "config", "user.name", _GIT_USER_NAME],
        cwd=tmp_path,
    )
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _run_git(git_executable, ["-C", str(repo), "add", "--", "README.md"], cwd=tmp_path)
    _run_git(git_executable, ["-C", str(repo), "commit", "--quiet", "-m", "initial"], cwd=tmp_path)
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\nprintf hook-ran > {canary}\n", encoding="utf-8")
    hook.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    base = _run_git(git_executable, ["-C", str(repo), "rev-parse", "HEAD"], cwd=tmp_path)
    return repo, base, canary


@pytest.fixture
def workspace_context(
    tmp_path: Path,
    git_executable: Path,
) -> tuple[GitWorktreeManager, GitWorktreeManager, Path]:
    factory_home = tmp_path / "factory-home"
    artifact_store = FilesystemArtifactStore(factory_home)
    runner = AsyncioProcessRunner(
        artifact_store,
        sanitizer_factory=StreamingOutputSanitizer,
    )
    return (
        GitWorktreeManager(runner, artifact_store, git_executable),
        GitWorktreeManager(runner, artifact_store, git_executable),
        factory_home,
    )


def _request(repository: Path, factory_home: Path, base: str) -> WorkspaceRequest:
    return WorkspaceRequest(
        repository=repository,
        factory_home=factory_home,
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-007"),
        base_commit=base,
    )


@pytest.mark.asyncio
async def test_prepare_is_idempotent_and_isolated(
    repository: tuple[Path, str, Path],
    workspace_context: tuple[GitWorktreeManager, GitWorktreeManager, Path],
    git_executable: Path,
) -> None:
    repo, base, canary = repository
    manager, _, factory_home = workspace_context
    request = _request(repo, factory_home, base)

    workspace = await manager.prepare(request)
    reopened = await manager.prepare(request)
    snapshot = await manager.inspect(workspace)

    assert reopened == workspace
    assert workspace.worktree_path == (
        factory_home / "worktrees" / "repo" / "run-abc123def456" / "TASK-007"
    )
    assert snapshot.head_commit == base
    assert snapshot.branch_name == workspace.branch_name
    assert snapshot.clean
    assert not canary.exists()
    assert _run_git(git_executable, ["-C", str(repo), "rev-parse", "HEAD"], cwd=repo) == base
    assert (
        _run_git(
            git_executable,
            ["-C", str(workspace.worktree_path), "rev-parse", "HEAD"],
            cwd=repo,
        )
        == base
    )

    (workspace.worktree_path / "new.txt").write_text("change\n", encoding="utf-8")
    changed = await manager.inspect(workspace)
    assert changed.clean is False
    assert "new.txt" in changed.changed_files
    await manager.clean(workspace, confirm=True)
    manager.close()


@pytest.mark.asyncio
async def test_workspace_inspect_cli_reports_identity(
    repository: tuple[Path, str, Path],
    workspace_context: tuple[GitWorktreeManager, GitWorktreeManager, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base, _ = repository
    manager, _, factory_home = workspace_context
    workspace = await manager.prepare(_request(repo, factory_home, base))
    monkeypatch.setenv("AIF_FACTORY_HOME", str(factory_home))

    assert await asyncio.to_thread(cli.main, ["workspace", "inspect", workspace.run_id.value]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == workspace.run_id.value
    assert payload["workspaces"][0]["base_commit"] == base
    assert payload["workspaces"][0]["path"] == str(workspace.worktree_path)
    await manager.clean(workspace, confirm=True)
    manager.close()


@pytest.mark.asyncio
async def test_single_writer_lock(
    repository: tuple[Path, str, Path],
    workspace_context: tuple[GitWorktreeManager, GitWorktreeManager, Path],
) -> None:
    repo, base, _ = repository
    manager_one, manager_two, factory_home = workspace_context
    request = _request(repo, factory_home, base)

    workspace = await manager_one.prepare(request)

    with pytest.raises(WorkspaceLockError):
        await manager_two.prepare(request)

    incompatible = WorkspaceRequest(
        repository=repo,
        factory_home=factory_home,
        run_id=request.run_id,
        task_id=request.task_id,
        base_commit=base,
        branch_name="aif/run-abc123def456/TASK-OTHER",
    )
    with pytest.raises(WorkspaceLockError):
        await manager_two.prepare(incompatible)
    manager_one.close()
    manager_two.close()
    assert workspace.lock_path.exists()


@pytest.mark.asyncio
async def test_invalid_lease_token_cannot_release_borrowed_lock(
    repository: tuple[Path, str, Path],
    workspace_context: tuple[GitWorktreeManager, GitWorktreeManager, Path],
) -> None:
    repo, base, _ = repository
    manager_one, manager_two, factory_home = workspace_context
    request = _request(repo, factory_home, base)
    workspace = await manager_one.prepare(request)
    lease = manager_one.borrow_lock_lease(workspace)

    manager_one._return_lock_lease(  # pyright: ignore[reportPrivateUsage]
        workspace.lock_path,
        "invalid-lease-token",
    )
    manager_one.close()

    assert not lease.active
    with pytest.raises(WorkspaceLockError):
        await manager_two.prepare(request)

    lease.close()
    reopened = await manager_two.prepare(request)
    assert reopened == workspace
    manager_two.close()


@pytest.mark.asyncio
async def test_replaced_lock_path_invalidates_active_lease(
    repository: tuple[Path, str, Path],
    workspace_context: tuple[GitWorktreeManager, GitWorktreeManager, Path],
) -> None:
    repo, base, _ = repository
    manager_one, manager_two, factory_home = workspace_context
    request = _request(repo, factory_home, base)
    workspace = await manager_one.prepare(request)
    lease = manager_one.borrow_lock_lease(workspace)
    preserved = workspace.lock_path.with_suffix(".preserved")
    workspace.lock_path.rename(preserved)
    workspace.lock_path.write_text(
        f"{workspace.run_id.value}\n{workspace.task_id.value}\n",
        encoding="ascii",
    )
    workspace.lock_path.chmod(0o600)

    assert not lease.active
    replacement = await manager_two.prepare(request)
    assert replacement == workspace

    lease.close()
    manager_one.close()
    manager_two.close()
    workspace.lock_path.unlink()
    preserved.rename(workspace.lock_path)


@pytest.mark.asyncio
async def test_lock_swap_during_acquisition_fails_before_git_effect(
    repository: tuple[Path, str, Path],
    workspace_context: tuple[GitWorktreeManager, GitWorktreeManager, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, _ = repository
    manager_one, manager_two, factory_home = workspace_context
    request = _request(repo, factory_home, base)
    expected_lock = factory_home / "locks" / "repo" / request.run_id.value / "TASK-007.lock"
    preserved = expected_lock.with_suffix(".opened")
    original_open = os.open
    swapped = False

    def swap_after_open(
        path: str | bytes | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if Path(os.fsdecode(path)) == expected_lock and flags & os.O_RDWR and not swapped:
            expected_lock.rename(preserved)
            expected_lock.write_bytes(b"")
            expected_lock.chmod(0o600)
            swapped = True
        return fd

    monkeypatch.setattr(worktrees_module.os, "open", swap_after_open)
    with pytest.raises(WorkspaceLockError):
        await manager_one.prepare(request)
    monkeypatch.setattr(worktrees_module.os, "open", original_open)

    expected_lock.unlink()
    preserved.rename(expected_lock)
    workspace = await manager_two.prepare(request)
    assert workspace.lock_path == expected_lock
    manager_two.close()


@pytest.mark.asyncio
async def test_rejects_escape_and_never_runs_hooks(
    repository: tuple[Path, str, Path],
    workspace_context: tuple[GitWorktreeManager, GitWorktreeManager, Path],
) -> None:
    repo, base, canary = repository
    manager, _, factory_home = workspace_context
    request = _request(repo, factory_home, base)
    outside = factory_home.parent / "outside"
    outside.mkdir()
    expected_path = (
        factory_home / "worktrees" / "repo" / request.run_id.value / request.task_id.value
    )
    expected_path.parent.mkdir(parents=True)
    expected_path.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspacePolicyError):
        await manager.prepare(request)
    assert not canary.exists()
    assert outside.exists()
    expected_path.unlink()
    manager.close()

    workspace = await manager.prepare(request)
    escaped = workspace.__class__(
        repository=workspace.repository,
        factory_home=workspace.factory_home,
        worktree_path=outside,
        lock_path=workspace.lock_path,
        run_id=workspace.run_id,
        task_id=workspace.task_id,
        base_commit=workspace.base_commit,
        branch_name=workspace.branch_name,
    )
    with pytest.raises((WorkspacePolicyError, WorkspaceIdentityError)):
        await manager.inspect(escaped)
    await manager.clean(workspace, confirm=True)
    manager.close()


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
