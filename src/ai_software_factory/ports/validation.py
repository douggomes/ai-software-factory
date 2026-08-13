"""Validation port — deterministic gate evaluation and immutable snapshots.

A ``ValidationGate`` never trusts model/worker output: it evaluates only
independently observable facts (changed paths, diff text, process exit
status) captured once, before any gate runs. Gates are pure over that data
except ``CommandGate``, whose entire purpose is to execute one authorized
process — I/O and side effects stay confined to that single gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from ai_software_factory.core.evaluation_workspace import RepositoryEvidence
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.process_models import ArtifactReference

_SNAPSHOT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^val-[a-z0-9]{12}$")
_SHA256_HEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(Exception):
    """Base class for validation port failures."""


class GateExecutionError(ValidationError):
    """Raised when a gate cannot produce a result at all (not a gate failure)."""


class SnapshotPersistenceError(ValidationError):
    """Raised when a computed snapshot cannot be safely persisted."""


class GateStatus(Enum):
    """Outcome of one gate, or of an entire validation snapshot."""

    PASSED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class SnapshotId:
    """Unique identifier for one immutable validation snapshot."""

    value: str

    def __post_init__(self) -> None:
        if not _SNAPSHOT_ID_PATTERN.match(self.value):
            raise ValueError(f"invalid SnapshotId format: {self.value!r}")


@dataclass(frozen=True, slots=True)
class GateFinding:
    """Structured evidence for one gate observation.

    Never carries a raw secret value: ``fingerprint`` is a digest, and
    ``message`` must describe the finding without quoting matched content.
    """

    code: str
    message: str
    path: str | None = None
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("GateFinding.code must be non-empty")
        if not self.message:
            raise ValueError("GateFinding.message must be non-empty")
        if self.fingerprint is not None and not _SHA256_HEX_PATTERN.match(self.fingerprint):
            raise ValueError(f"invalid fingerprint format: {self.fingerprint!r}")


@dataclass(frozen=True, slots=True)
class GateResult:
    """Immutable outcome of one gate evaluation."""

    gate_name: str
    status: GateStatus
    findings: tuple[GateFinding, ...] = ()
    artifact_refs: tuple[ArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        if not self.gate_name:
            raise ValueError("GateResult.gate_name must be non-empty")


@dataclass(frozen=True, slots=True)
class ChangedFileEvidence:
    """Bounded current content for one independently discovered changed path.

    `content` is never serialized into a snapshot. It exists only long
    enough for deterministic gates to inspect text and binary changes. A
    path that cannot be read safely carries `scan_error` and must fail
    closed in the secret gate.
    """

    path: str
    content: bytes
    content_hash: str
    deleted: bool = False
    scan_error: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("ChangedFileEvidence.path must be non-empty")
        if not _SHA256_HEX_PATTERN.match(self.content_hash):
            raise ValueError(f"invalid changed-file hash: {self.content_hash!r}")
        if self.deleted and self.content:
            raise ValueError("deleted changed-file evidence cannot carry content")


@dataclass(frozen=True, slots=True)
class GateContext:
    """Independently captured facts a gate evaluates — never worker-reported.

    ``changed_files``, ``diff_text`` and ``diff_check_output`` are captured
    under the task's writer lock. The evaluator captures them again after
    command gates and invalidates approval if the worktree changed.
    """

    run_id: RunId
    task_id: TaskId
    worktree_path: Path
    base_commit: str
    allowed_paths: tuple[str, ...]
    changed_files: tuple[str, ...]
    changed_file_evidence: tuple[ChangedFileEvidence, ...]
    diff_text: str
    diff_check_output: str
    evaluation_snapshot_id: str | None = None
    evaluation_manifest_hash: str | None = None
    evaluation_identity_hash: str | None = None
    isolation_backend: str | None = None
    isolation_policy_hash: str | None = None
    repository_evidence: RepositoryEvidence | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "worktree_path", Path(self.worktree_path))
        if not self.worktree_path.is_absolute():
            raise ValueError("GateContext.worktree_path must be absolute")
        evidence_paths = tuple(item.path for item in self.changed_file_evidence)
        if self.repository_evidence is None and evidence_paths != self.changed_files:
            raise ValueError("changed_file_evidence must correspond exactly to changed_files")
        if (
            self.repository_evidence is not None
            and self.changed_files != self.repository_evidence.changed_paths
        ):
            raise ValueError("changed_files must correspond to repository evidence")
        _validate_evaluation_evidence(
            self.evaluation_snapshot_id,
            self.evaluation_manifest_hash,
            self.evaluation_identity_hash,
            self.isolation_backend,
            self.isolation_policy_hash,
        )


@runtime_checkable
class ValidationGate(Protocol):
    """One deterministic, independently verifiable evaluation step."""

    @property
    def name(self) -> str:
        """Stable, human-readable gate identifier (e.g. ``scope``)."""
        ...

    @property
    def configuration_key(self) -> str:
        """Stable non-secret identity of the gate configuration."""
        ...

    async def evaluate(self, context: GateContext) -> GateResult:
        """Evaluate ``context`` and return an immutable result.

        Never raises for a *failing* evaluation — that is expressed as
        ``GateStatus.FAILED`` with findings. Raises ``GateExecutionError``
        only when the gate itself cannot run (e.g. process I/O failure).
        """
        ...


@dataclass(frozen=True, slots=True)
class ValidationSnapshot:
    """Immutable, once-written record of one full gate pipeline execution."""

    snapshot_id: SnapshotId
    run_id: RunId
    task_id: TaskId
    base_commit: str
    profile_name: str
    profile_hash: str
    diff_hash: str
    status: GateStatus
    gate_results: tuple[GateResult, ...]
    created_at: datetime
    evaluation_snapshot_id: str | None = None
    evaluation_manifest_hash: str | None = None
    evaluation_identity_hash: str | None = None
    isolation_backend: str | None = None
    isolation_policy_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.profile_name:
            raise ValueError("ValidationSnapshot.profile_name must be non-empty")
        if not _SHA256_HEX_PATTERN.match(self.profile_hash):
            raise ValueError(f"invalid profile_hash format: {self.profile_hash!r}")
        if not _SHA256_HEX_PATTERN.match(self.diff_hash):
            raise ValueError(f"invalid diff_hash format: {self.diff_hash!r}")
        if not self.gate_results:
            raise ValueError("ValidationSnapshot.gate_results must be non-empty")
        expected = (
            GateStatus.FAILED
            if any(result.status is GateStatus.FAILED for result in self.gate_results)
            else GateStatus.PASSED
        )
        if self.status is not expected:
            raise ValueError("ValidationSnapshot.status is inconsistent with gate_results")
        _validate_evaluation_evidence(
            self.evaluation_snapshot_id,
            self.evaluation_manifest_hash,
            self.evaluation_identity_hash,
            self.isolation_backend,
            self.isolation_policy_hash,
        )


def _validate_evaluation_evidence(
    snapshot_id: str | None,
    manifest_hash: str | None,
    identity_hash: str | None,
    isolation_backend: str | None,
    isolation_policy_hash: str | None,
) -> None:
    snapshot_values = (snapshot_id, manifest_hash, identity_hash)
    if any(value is not None for value in snapshot_values) and any(
        value is None for value in snapshot_values
    ):
        raise ValueError("evaluation snapshot evidence must be complete")
    if snapshot_id is not None and not re.fullmatch(r"snap-[0-9a-f]{12}", snapshot_id):
        raise ValueError("evaluation snapshot id is invalid")
    for label, value in (
        ("evaluation manifest hash", manifest_hash),
        ("evaluation identity hash", identity_hash),
    ):
        if value is not None and not _SHA256_HEX_PATTERN.match(value):
            raise ValueError(f"invalid {label}: {value!r}")
    isolation_values = (isolation_backend, isolation_policy_hash)
    if any(value is not None for value in isolation_values) and any(
        value is None for value in isolation_values
    ):
        raise ValueError("isolation evidence must be complete")
    if isolation_backend is not None and isolation_backend not in {"docker", "podman"}:
        raise ValueError("isolation backend is invalid")
    if isolation_policy_hash is not None and not _SHA256_HEX_PATTERN.match(isolation_policy_hash):
        raise ValueError("isolation policy hash is invalid")
