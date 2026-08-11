"""Shared behavioral contract for ProcessRunner implementations."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import cast

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.core.ids import AttemptId, RunId
from ai_software_factory.core.process_models import ProcessPolicy, ProcessRequest
from ai_software_factory.ports.artifacts import ArtifactRef
from ai_software_factory.ports.processes import ProcessRunner


def _fake_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-contract.py"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\nprint(sys.argv[1])\n",
        encoding="utf-8",
    )
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return executable


def _request(executable: Path, cwd: Path) -> ProcessRequest:
    return ProcessRequest(
        argv=(str(executable), "contract-argument"),
        cwd=cwd,
        policy=ProcessPolicy(allowed_executables=(executable,), allowed_cwd_roots=(cwd,)),
        run_id=RunId("run-abc123def456"),
        attempt_id=AttemptId("att-abc123def456"),
    )


async def test_process_runner_contract_returns_sanitized_artifact_refs(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    runner: ProcessRunner = AsyncioProcessRunner(store)

    result = await runner.run(_request(executable, tmp_path))

    assert result.succeeded
    assert result.stdout_ref is not None
    assert result.stderr_ref is not None
    assert store.read(cast(ArtifactRef, result.stdout_ref)) == b"contract-argument\n"
    assert store.read(cast(ArtifactRef, result.stderr_ref)) == b""
    assert result.truncated is False
    assert os.path.commonpath([str(result.stdout_ref.relative_path), "process"]) == "process"
