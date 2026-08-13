"""Deterministic gate evaluator — runs a profile and persists one snapshot.

The evaluator never overwrites a prior snapshot: ``ArtifactStore.put`` is
create-exclusive, so a colliding id fails closed instead of silently
replacing evidence (``snapshot_overwrite: false``).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from ai_software_factory.core.process_models import ArtifactReference
from ai_software_factory.evaluation.models import ValidationProfile
from ai_software_factory.ports.artifacts import (
    ArtifactError,
    ArtifactKind,
    ArtifactRef,
    ArtifactStore,
)
from ai_software_factory.ports.validation import (
    GateContext,
    GateExecutionError,
    GateFinding,
    GateResult,
    GateStatus,
    SnapshotId,
    SnapshotPersistenceError,
    ValidationSnapshot,
)


def _new_snapshot_id() -> SnapshotId:
    return SnapshotId(f"val-{uuid.uuid4().hex[:12]}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _diff_hash(diff_text: str) -> str:
    return hashlib.sha256(diff_text.encode("utf-8", errors="surrogateescape")).hexdigest()


def _overall_status(results: tuple[GateResult, ...]) -> GateStatus:
    if any(result.status is GateStatus.FAILED for result in results):
        return GateStatus.FAILED
    return GateStatus.PASSED


class Evaluator:
    """Runs every gate in a profile, in order, against one bound context."""

    def __init__(
        self,
        context: GateContext,
        artifact_store: ArtifactStore,
        *,
        snapshot_id_factory: Callable[[], SnapshotId] = _new_snapshot_id,
        clock: Callable[[], datetime] = _utc_now,
        context_refresh: Callable[[], GateContext] | None = None,
    ) -> None:
        self._context = context
        self._artifact_store = artifact_store
        self._snapshot_id_factory = snapshot_id_factory
        self._clock = clock
        self._context_refresh = context_refresh

    async def run(self, profile: ValidationProfile) -> ValidationSnapshot:
        """Execute every gate in ``profile.gates``, in stable declared order.

        Every gate runs even after an earlier one fails, so one snapshot
        always reports every gate's outcome. The snapshot is persisted
        exactly once, under a freshly generated id, and is never overwritten.
        """
        results: list[GateResult] = []
        for gate in profile.gates:
            try:
                results.append(await gate.evaluate(self._context))
            except GateExecutionError:
                results.append(
                    GateResult(
                        gate_name=gate.name,
                        status=GateStatus.FAILED,
                        findings=(
                            GateFinding(
                                code="GATE_EXECUTION_ERROR",
                                message="gate could not execute under the authorized policy",
                            ),
                        ),
                    )
                )
        snapshot_context = self._context
        if self._context_refresh is not None:
            refreshed = self._context_refresh()
            if _context_hash(refreshed) != _context_hash(self._context):
                snapshot_context = refreshed
                results = await _refresh_structural_results(profile, tuple(results), refreshed)
        snapshot = ValidationSnapshot(
            snapshot_id=self._snapshot_id_factory(),
            run_id=snapshot_context.run_id,
            task_id=snapshot_context.task_id,
            base_commit=snapshot_context.base_commit,
            profile_name=profile.name,
            profile_hash=profile.config_hash,
            diff_hash=_diff_hash(snapshot_context.diff_text),
            status=_overall_status(tuple(results)),
            gate_results=tuple(results),
            created_at=self._clock(),
        )
        self._persist(snapshot)
        return snapshot

    def _persist(self, snapshot: ValidationSnapshot) -> None:
        try:
            payload = _snapshot_to_json(snapshot, self._artifact_store).encode("utf-8")
            ref = ArtifactRef(
                run_id=snapshot.run_id,
                relative_path=f"validations/{snapshot.snapshot_id.value}.json",
                kind=ArtifactKind.VALIDATION,
            )
            self._artifact_store.put(ref, payload)
        except (ArtifactError, OSError, ValueError) as error:
            raise SnapshotPersistenceError("validation snapshot could not be persisted") from error


def _snapshot_to_json(snapshot: ValidationSnapshot, artifact_store: ArtifactStore) -> str:
    return json.dumps(
        _snapshot_to_dict(snapshot, artifact_store),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )


def _snapshot_to_dict(
    snapshot: ValidationSnapshot, artifact_store: ArtifactStore
) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id.value,
        "run_id": snapshot.run_id.value,
        "task_id": snapshot.task_id.value,
        "base_commit": snapshot.base_commit,
        "profile_name": snapshot.profile_name,
        "profile_hash": snapshot.profile_hash,
        "diff_hash": snapshot.diff_hash,
        "status": snapshot.status.name,
        "created_at": snapshot.created_at.isoformat(),
        "gate_results": [
            _gate_result_to_dict(result, artifact_store) for result in snapshot.gate_results
        ],
    }


def _gate_result_to_dict(result: GateResult, artifact_store: ArtifactStore) -> dict[str, object]:
    return {
        "gate_name": result.gate_name,
        "status": result.status.name,
        "findings": [
            {
                "code": finding.code,
                "message": finding.message,
                "path": finding.path,
                "fingerprint": finding.fingerprint,
            }
            for finding in result.findings
        ],
        "artifact_refs": [
            _artifact_ref_to_dict(ref, artifact_store) for ref in result.artifact_refs
        ],
    }


def _artifact_ref_to_dict(
    reference: ArtifactReference, artifact_store: ArtifactStore
) -> dict[str, object]:
    ref = ArtifactRef(run_id=reference.run_id, relative_path=reference.relative_path)
    payload = artifact_store.read(ref)
    return {
        "relative_path": reference.relative_path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _context_hash(context: GateContext) -> str:
    digest = hashlib.sha256()
    digest.update(context.diff_text.encode("utf-8", errors="surrogateescape"))
    digest.update(b"\x00")
    digest.update(context.diff_check_output.encode("utf-8", errors="surrogateescape"))
    for evidence in context.changed_file_evidence:
        digest.update(b"\x00")
        digest.update(evidence.path.encode("utf-8"))
        digest.update(evidence.content_hash.encode("ascii"))
        digest.update(str(evidence.deleted).encode("ascii"))
        digest.update((evidence.scan_error or "").encode("utf-8"))
    return digest.hexdigest()


async def _refresh_structural_results(
    profile: ValidationProfile,
    original_results: tuple[GateResult, ...],
    context: GateContext,
) -> list[GateResult]:
    refreshed_results: list[GateResult] = []
    structural_names = {"scope", "diff", "secrets"}
    for gate, result in zip(profile.gates, original_results, strict=True):
        if gate.name not in structural_names:
            refreshed_results.append(result)
            continue
        current = await gate.evaluate(context)
        if gate.name == "diff":
            current = replace(
                current,
                status=GateStatus.FAILED,
                findings=(
                    *current.findings,
                    GateFinding(
                        code="WORKTREE_CHANGED_DURING_VALIDATION",
                        message="worktree changed while mandatory gates were running",
                    ),
                ),
            )
        refreshed_results.append(current)
    return refreshed_results
