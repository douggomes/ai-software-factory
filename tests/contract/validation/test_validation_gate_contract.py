"""Shared structural contract for every ValidationGate implementation."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.process_models import ProcessPolicy, TrustProfile
from ai_software_factory.evaluation.gates import CommandGate, DiffGate, ScopeGate, SecretGate
from ai_software_factory.ports.validation import (
    ChangedFileEvidence,
    GateContext,
    GateStatus,
    ValidationGate,
)


def _context(tmp_path: Path) -> GateContext:
    return GateContext(
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-999"),
        worktree_path=tmp_path,
        base_commit="a" * 40,
        allowed_paths=("src/**",),
        changed_files=("src/module.py",),
        changed_file_evidence=(
            ChangedFileEvidence(
                path="src/module.py",
                content=b"value = 1\n",
                content_hash="9" * 64,
            ),
        ),
        diff_text="diff --git a/src/module.py b/src/module.py\n",
        diff_check_output="",
    )


_STRUCTURAL_GATES: tuple[ValidationGate, ...] = (ScopeGate(), DiffGate(), SecretGate())


@pytest.mark.parametrize("gate", _STRUCTURAL_GATES, ids=lambda gate: gate.name)
async def test_structural_gate_contract(gate: ValidationGate, tmp_path: Path) -> None:
    context = _context(tmp_path)

    result = await gate.evaluate(context)

    assert isinstance(gate, ValidationGate)
    assert result.gate_name == gate.name
    assert result.status in (GateStatus.PASSED, GateStatus.FAILED)
    assert all(finding.code and finding.message for finding in result.findings)


async def test_command_gate_contract(tmp_path: Path) -> None:
    executable = tmp_path / "ok.py"
    executable.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n", encoding="utf-8")
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    context = GateContext(
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-999"),
        worktree_path=tmp_path,
        base_commit="a" * 40,
        allowed_paths=("src/**",),
        changed_files=(),
        changed_file_evidence=(),
        diff_text="",
        diff_check_output="",
    )
    gate: ValidationGate = CommandGate(
        gate_name="ok",
        argv=(str(executable),),
        process_runner=AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer),
        process_policy=ProcessPolicy(
            allowed_executables=(executable,), allowed_cwd_roots=(tmp_path,)
        ),
        trust_profile=TrustProfile.TRUSTED,
    )

    result = await gate.evaluate(context)

    assert isinstance(gate, ValidationGate)
    assert result.gate_name == "ok"
    assert result.status is GateStatus.PASSED
    stdout_ref, stderr_ref = result.artifact_refs
    assert stdout_ref.relative_path.endswith("stdout.bin")
    assert stderr_ref.relative_path.endswith("stderr.bin")
