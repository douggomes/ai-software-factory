"""Structural contract for evaluation snapshot implementations."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_software_factory.adapters.git.evaluation_workspace import GitEvaluationWorkspace
from ai_software_factory.core.evaluation_workspace import (
    DEFAULT_MAX_EVALUATION_BYTES,
    DEFAULT_MAX_EVALUATION_FILES,
    EvaluationCaptureRequest,
    EvaluationModelError,
    EvaluationSnapshot,
    FileClassification,
    ManifestEntry,
    RepositoryEvidence,
    SecretFinding,
    SnapshotLifecycle,
)
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.workspace_models import Workspace
from ai_software_factory.ports.artifacts import ArtifactKind, ArtifactRef
from ai_software_factory.ports.evaluation_workspace import (
    EvaluationWorkspace,
    RepositoryInspection,
)

_EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def _snapshot_factory(tmp_path: Path) -> Callable[[], EvaluationSnapshot]:
    workspace = Workspace(
        repository=tmp_path / "repo",
        factory_home=tmp_path / "factory",
        worktree_path=tmp_path / "factory/worktrees/repo/run-abc123def456/TASK-035",
        lock_path=tmp_path / "factory/locks/repo/run-abc123def456/TASK-035.lock",
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-035"),
        base_commit="a" * 40,
        branch_name="aif/run-abc123def456/TASK-035",
    )
    evidence = RepositoryEvidence(
        tracked_paths=("safe.txt",),
        untracked_paths=(),
        ignored_paths=(),
        changed_paths=(),
        binary_paths=(),
        secret_findings=(),
        diff_hash=_EMPTY_HASH,
    )

    def build() -> EvaluationSnapshot:
        return EvaluationSnapshot(
            snapshot_id="snap-111111111111",
            workspace=workspace,
            root=tmp_path / "factory/evaluations/repo/run-abc123def456/TASK-035/snapshot",
            head_commit="a" * 40,
            entries=(
                ManifestEntry(
                    path="safe.txt",
                    classification=FileClassification.TRACKED,
                    present=True,
                    included=True,
                    size_bytes=0,
                    sha256=_EMPTY_HASH,
                    binary=False,
                ),
            ),
            evidence=evidence,
            manifest_ref=ArtifactRef(
                run_id=workspace.run_id,
                relative_path="evaluations/snap-111111111111/manifest.json",
                kind=ArtifactKind.VALIDATION,
            ),
            manifest_hash=_EMPTY_HASH,
            identity_hash=_EMPTY_HASH,
        )

    return build


def test_git_adapter_implements_narrow_snapshot_contracts() -> None:
    assert issubclass(GitEvaluationWorkspace, EvaluationWorkspace)
    assert issubclass(GitEvaluationWorkspace, RepositoryInspection)
    assert tuple(EvaluationCaptureRequest.__dataclass_fields__) == (
        "workspace",
        "max_files",
        "max_total_bytes",
    )
    assert tuple(EvaluationSnapshot.__dataclass_fields__) == (
        "snapshot_id",
        "workspace",
        "root",
        "head_commit",
        "entries",
        "evidence",
        "manifest_ref",
        "manifest_hash",
        "identity_hash",
        "lifecycle",
    )
    lifecycle_default = EvaluationSnapshot.__dataclass_fields__["lifecycle"].default
    assert lifecycle_default is SnapshotLifecycle.VERIFIED
    assert tuple(RepositoryEvidence.__dataclass_fields__)[-1] == "diff_hash"


def test_evaluation_contract_defaults_limits_and_immutability(tmp_path: Path) -> None:
    build = _snapshot_factory(tmp_path)
    snapshot = build()

    assert snapshot.lifecycle is SnapshotLifecycle.VERIFIED
    assert snapshot.entries[0].classification is FileClassification.TRACKED
    assert (
        EvaluationCaptureRequest.__dataclass_fields__["max_files"].default
        == DEFAULT_MAX_EVALUATION_FILES
    )
    assert (
        EvaluationCaptureRequest.__dataclass_fields__["max_total_bytes"].default
        == DEFAULT_MAX_EVALUATION_BYTES
    )
    with pytest.raises(EvaluationModelError):
        EvaluationCaptureRequest(
            snapshot.workspace,
            max_files=DEFAULT_MAX_EVALUATION_FILES + 1,
        )
    with pytest.raises(EvaluationModelError):
        EvaluationCaptureRequest(
            snapshot.workspace,
            max_total_bytes=DEFAULT_MAX_EVALUATION_BYTES + 1,
        )
    with pytest.raises((AttributeError, TypeError)):
        snapshot.lifecycle = SnapshotLifecycle.VERIFIED  # type: ignore[misc]


def test_evaluation_contract_rejects_unverifiable_evidence(tmp_path: Path) -> None:
    build = _snapshot_factory(tmp_path)
    snapshot = build()

    with pytest.raises(EvaluationModelError):
        SecretFinding(kind="token", path="../escape", fingerprint=_EMPTY_HASH)
    with pytest.raises(EvaluationModelError):
        EvaluationSnapshot(
            snapshot_id=snapshot.snapshot_id,
            workspace=snapshot.workspace,
            root=snapshot.root,
            head_commit=snapshot.head_commit,
            entries=snapshot.entries,
            evidence=snapshot.evidence,
            manifest_ref=snapshot.manifest_ref,
            manifest_hash="not-a-hash",
            identity_hash=snapshot.identity_hash,
        )
