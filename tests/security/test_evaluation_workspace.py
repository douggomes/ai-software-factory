"""Abuse cases for persisted workspace paths and symlink swaps."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_software_factory.adapters.git import evaluation_workspace as evaluation_module
from ai_software_factory.adapters.git.evaluation_workspace import GitEvaluationWorkspace
from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.core.evaluation_workspace import EvaluationCaptureRequest, SecretFinding
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.process_models import ProcessRequest, ProcessResult
from ai_software_factory.core.workspace_models import WorkspaceRequest
from ai_software_factory.ports.evaluation_workspace import EvaluationWorkspacePolicyError


@pytest.mark.asyncio
async def test_external_symlink_and_swapped_worktree_fail_closed(  # noqa: C901, PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_path = shutil.which("git")
    if git_path is None:
        pytest.fail("git is required for evaluation workspace security tests")
    git = Path(git_path).resolve()
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(git, repository, "init", "--quiet")
    _git(git, repository, "config", "user.email", "security@example.invalid")
    _git(git, repository, "config", "user.name", "Security Test")
    (repository / "safe.txt").write_text("safe\n", encoding="utf-8")
    _git(git, repository, "add", "--", "safe.txt")
    _git(git, repository, "commit", "--quiet", "-m", "initial")
    base = _git(git, repository, "rev-parse", "HEAD")
    factory_home = tmp_path / "factory-home"
    store = FilesystemArtifactStore(factory_home)
    runner = AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer)
    manager = GitWorktreeManager(runner, store, git)
    workspace = await manager.prepare(
        WorkspaceRequest(
            repository=repository,
            factory_home=factory_home,
            run_id=RunId("run-abc123def456"),
            task_id=TaskId("TASK-035"),
            base_commit=base,
        )
    )
    adapter = GitEvaluationWorkspace(runner, store, git, manager)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("must-not-be-read\n", encoding="utf-8")
    forged = workspace.__class__(
        repository=workspace.repository,
        factory_home=workspace.factory_home,
        worktree_path=outside,
        lock_path=workspace.lock_path,
        run_id=workspace.run_id,
        task_id=workspace.task_id,
        base_commit=workspace.base_commit,
        branch_name=workspace.branch_name,
    )

    with pytest.raises(EvaluationWorkspacePolicyError) as external_error:
        await adapter.capture(EvaluationCaptureRequest(forged))
    assert str(outside) not in str(external_error.value)

    sibling_parent = tmp_path / "sibling"
    sibling_parent.mkdir()
    sibling_repository = sibling_parent / repository.name
    _git(git, tmp_path, "clone", "--quiet", "--", str(repository), str(sibling_repository))
    confused = workspace.__class__(
        repository=sibling_repository,
        factory_home=workspace.factory_home,
        worktree_path=workspace.worktree_path,
        lock_path=workspace.lock_path,
        run_id=workspace.run_id,
        task_id=workspace.task_id,
        base_commit=workspace.base_commit,
        branch_name=workspace.branch_name,
    )
    with pytest.raises(EvaluationWorkspacePolicyError):
        await adapter.capture(EvaluationCaptureRequest(confused))

    sibling_worktree = await manager.prepare(
        WorkspaceRequest(
            repository=repository,
            factory_home=factory_home,
            run_id=workspace.run_id,
            task_id=TaskId("TASK-034"),
            base_commit=base,
        )
    )
    primary_git_link = (workspace.worktree_path / ".git").read_bytes()
    crossed_git_link = (sibling_worktree.worktree_path / ".git").read_bytes()
    (workspace.worktree_path / ".git").write_bytes(crossed_git_link)
    try:
        with pytest.raises(EvaluationWorkspacePolicyError):
            await adapter.capture(EvaluationCaptureRequest(workspace))
    finally:
        (workspace.worktree_path / ".git").write_bytes(primary_git_link)

    original_git_state = adapter._git_state  # pyright: ignore[reportPrivateUsage]
    git_state_calls = 0

    async def swap_git_link_after_initial_validation(
        current_workspace: object,
        source_identity: object,
        control: object,
    ) -> object:
        nonlocal git_state_calls
        state = await original_git_state(
            current_workspace,  # pyright: ignore[reportArgumentType]
            source_identity,  # pyright: ignore[reportArgumentType]
            control,  # pyright: ignore[reportArgumentType]
        )
        git_state_calls += 1
        if git_state_calls == 1:
            (workspace.worktree_path / ".git").write_bytes(crossed_git_link)
        return state

    monkeypatch.setattr(adapter, "_git_state", swap_git_link_after_initial_validation)
    try:
        with pytest.raises(EvaluationWorkspacePolicyError):
            await adapter.capture(EvaluationCaptureRequest(workspace))
    finally:
        (workspace.worktree_path / ".git").write_bytes(primary_git_link)
        monkeypatch.setattr(adapter, "_git_state", original_git_state)

    class SwapDuringGitRunner:
        async def run(self, request: ProcessRequest) -> ProcessResult:
            (workspace.worktree_path / ".git").write_bytes(crossed_git_link)
            try:
                return await runner.run(request)
            finally:
                (workspace.worktree_path / ".git").write_bytes(primary_git_link)

    descriptor_bound = GitEvaluationWorkspace(
        SwapDuringGitRunner(),
        store,
        git,
        manager,
        snapshot_id_factory=lambda: "snap-999999999999",
    )
    snapshot = await descriptor_bound.capture(EvaluationCaptureRequest(workspace))
    assert snapshot.head_commit == base
    assert snapshot.evidence.tracked_paths == ("safe.txt",)

    original_final_verify = evaluation_module._verify_final_source  # pyright: ignore[reportPrivateUsage]
    late_file = workspace.worktree_path / "late.txt"

    def create_late_file(*args: object, **kwargs: object) -> None:
        late_file.write_text("late\n", encoding="utf-8")
        original_final_verify(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(evaluation_module, "_verify_final_source", create_late_file)
    late_adapter = GitEvaluationWorkspace(
        runner,
        store,
        git,
        manager,
        snapshot_id_factory=lambda: "snap-aaaaaaaaaaaa",
    )
    try:
        with pytest.raises(evaluation_module.EvaluationWorkspaceChangedError):
            await late_adapter.capture(EvaluationCaptureRequest(workspace))
    finally:
        late_file.unlink(missing_ok=True)
        monkeypatch.setattr(evaluation_module, "_verify_final_source", original_final_verify)

    git_directory = Path(primary_git_link.decode().strip().removeprefix("gitdir: "))
    head_data = (git_directory / "HEAD").read_text(encoding="ascii")
    head_reference = head_data.removeprefix("ref: ").strip()
    loose_ref = repository / ".git" / head_reference
    original_ref = loose_ref.read_bytes()
    heads_directory = repository / ".git" / "refs" / "heads"
    preserved_heads = heads_directory.with_name("heads-preserved")
    external_heads = tmp_path / "external-heads"
    shutil.copytree(heads_directory, external_heads)
    heads_directory.rename(preserved_heads)
    heads_directory.symlink_to(external_heads, target_is_directory=True)
    try:
        with pytest.raises(EvaluationWorkspacePolicyError):
            await adapter.capture(EvaluationCaptureRequest(workspace))
    finally:
        heads_directory.unlink()
        preserved_heads.rename(heads_directory)

    def advance_head_before_final_verify(*args: object, **kwargs: object) -> None:
        loose_ref.write_bytes(b"b" * 40 + b"\n")
        original_final_verify(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(evaluation_module, "_verify_final_source", advance_head_before_final_verify)
    head_adapter = GitEvaluationWorkspace(
        runner,
        store,
        git,
        manager,
        snapshot_id_factory=lambda: "snap-bbbbbbbbbbbb",
    )
    try:
        with pytest.raises(evaluation_module.EvaluationWorkspaceChangedError):
            await head_adapter.capture(EvaluationCaptureRequest(workspace))
    finally:
        loose_ref.write_bytes(original_ref)
        monkeypatch.setattr(evaluation_module, "_verify_final_source", original_final_verify)

    exclude = repository / ".git" / "info" / "exclude"
    original_exclude = exclude.read_bytes()

    def change_exclude_before_final_verify(*args: object, **kwargs: object) -> None:
        exclude.write_bytes(original_exclude + b"late-secret\n")
        original_final_verify(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(
        evaluation_module, "_verify_final_source", change_exclude_before_final_verify
    )
    exclude_adapter = GitEvaluationWorkspace(
        runner,
        store,
        git,
        manager,
        snapshot_id_factory=lambda: "snap-cccccccccccc",
    )
    try:
        with pytest.raises(evaluation_module.EvaluationWorkspaceChangedError):
            await exclude_adapter.capture(EvaluationCaptureRequest(workspace))
    finally:
        exclude.write_bytes(original_exclude)
        monkeypatch.setattr(evaluation_module, "_verify_final_source", original_final_verify)

    original = workspace.worktree_path.with_name("TASK-035-original")
    workspace.worktree_path.rename(original)
    workspace.worktree_path.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(EvaluationWorkspacePolicyError) as symlink_error:
            await adapter.capture(EvaluationCaptureRequest(workspace))
        assert str(outside) not in str(symlink_error.value)
        assert (outside / "secret.txt").read_text(encoding="utf-8") == "must-not-be-read\n"
    finally:
        workspace.worktree_path.unlink()
        original.rename(workspace.worktree_path)

    original_open = evaluation_module._open_directory  # pyright: ignore[reportPrivateUsage]
    repository_component = workspace.worktree_path.parent.parent
    preserved_component = repository_component.with_name(repository_component.name + "-original")
    redirect_root = tmp_path / "redirected-worktrees"
    redirected_worktree = redirect_root / workspace.run_id.value / workspace.task_id.value
    redirected_worktree.mkdir(parents=True)
    sentinel = redirected_worktree / "external-sentinel.txt"
    sentinel.write_text("never-opened\n", encoding="utf-8")
    swapped = False

    def swap_intermediate(path: Path) -> int:
        nonlocal swapped
        if path == workspace.worktree_path and not swapped:
            repository_component.rename(preserved_component)
            repository_component.symlink_to(redirect_root, target_is_directory=True)
            swapped = True
        return original_open(path)

    monkeypatch.setattr(evaluation_module, "_open_directory", swap_intermediate)
    try:
        with pytest.raises(EvaluationWorkspacePolicyError):
            await adapter.capture(EvaluationCaptureRequest(workspace))
        assert sentinel.read_text(encoding="utf-8") == "never-opened\n"
    finally:
        monkeypatch.setattr(evaluation_module, "_open_directory", original_open)
        if repository_component.is_symlink():
            repository_component.unlink()
        if preserved_component.exists():
            preserved_component.rename(repository_component)
        manager.close()


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


def test_inventory_and_secret_evidence_limits_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "inventory"
    root.mkdir()
    for name in ("one", "two", "three"):
        (root / name).mkdir()
    root_fd = evaluation_module._open_directory(root)  # pyright: ignore[reportPrivateUsage]
    try:
        with pytest.raises(EvaluationWorkspacePolicyError):
            evaluation_module._inventory_source_paths(  # pyright: ignore[reportPrivateUsage]
                root_fd, 2
            )
    finally:
        os.close(root_fd)

    deep = root / "deep"
    deep.mkdir()
    (deep / "deeper").mkdir()
    monkeypatch.setattr(evaluation_module, "_MAX_INVENTORY_DEPTH", 1)
    root_fd = evaluation_module._open_directory(root)  # pyright: ignore[reportPrivateUsage]
    try:
        with pytest.raises(EvaluationWorkspacePolicyError):
            evaluation_module._inventory_source_paths(  # pyright: ignore[reportPrivateUsage]
                root_fd, 100
            )
    finally:
        os.close(root_fd)

    monkeypatch.setattr(evaluation_module, "_MAX_SECRET_FINDINGS", 1)
    findings = {
        SecretFinding("token", "one.txt", "a" * 64),
        SecretFinding("token", "two.txt", "b" * 64),
    }
    with pytest.raises(EvaluationWorkspacePolicyError):
        evaluation_module._merge_secret_findings(  # pyright: ignore[reportPrivateUsage]
            set(), findings, 0
        )

    secret_file = root / "many-secrets.txt"
    secret_file.write_text(
        "token=first-unique-secret\ntoken=second-unique-secret\n", encoding="utf-8"
    )
    monkeypatch.setattr(evaluation_module, "_MAX_SECRET_FINDINGS", 1)
    root_fd = evaluation_module._open_directory(root)  # pyright: ignore[reportPrivateUsage]
    try:
        with pytest.raises(EvaluationWorkspacePolicyError):
            evaluation_module._scan_source_file(  # pyright: ignore[reportPrivateUsage]
                root_fd,
                secret_file.name,
                4096,
            )
    finally:
        os.close(root_fd)
