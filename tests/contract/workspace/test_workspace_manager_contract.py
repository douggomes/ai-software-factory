"""Shared contract for workspace manager behavior."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.workspace_models import WorkspaceRequest
from ai_software_factory.ports.workspace import WorkspaceManager


async def test_workspace_manager_contract(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.fail("git executable is required for workspace contract")
    repo, base = _create_repository(tmp_path, git)
    factory_home = tmp_path / "factory"
    store = FilesystemArtifactStore(factory_home)
    manager: WorkspaceManager = GitWorktreeManager(
        AsyncioProcessRunner(store), store, Path(git).resolve()
    )
    request = WorkspaceRequest(
        repository=repo,
        factory_home=factory_home,
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-007"),
        base_commit=base,
    )

    workspace = await manager.prepare(request)
    snapshot = await manager.inspect(workspace)

    assert snapshot.clean
    assert snapshot.head_commit == base
    await manager.clean(workspace, confirm=True)


def _create_repository(tmp_path: Path, git: str) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    subprocess.run([git, "init", "--quiet", str(repo)], check=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [git, "-C", str(repo), "config", "user.email", "contract@example.invalid"],
        check=True,
    )
    subprocess.run(  # noqa: S603
        [git, "-C", str(repo), "config", "user.name", "Contract"],
        check=True,
    )
    (repo / "file.txt").write_text("contract\n", encoding="utf-8")
    subprocess.run([git, "-C", str(repo), "add", "--", "file.txt"], check=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [git, "-C", str(repo), "commit", "--quiet", "-m", "initial"], check=True
    )
    base = subprocess.run(  # noqa: S603
        [git, "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return repo, base
