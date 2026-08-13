"""Shared behavioral contract for ProcessRunner implementations."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pytest

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.core.ids import AttemptId, RunId
from ai_software_factory.core.process_models import (
    DEFAULT_MAX_EXECUTABLE_BYTES,
    ProcessPolicy,
    ProcessRequest,
)
from ai_software_factory.ports.artifacts import ArtifactRef
from ai_software_factory.ports.output_sanitization import (
    OutputSanitizationError,
    OutputSanitizer,
)
from ai_software_factory.ports.processes import ProcessArtifactError, ProcessRunner


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


class _SubstituteSanitizer:
    def __init__(self) -> None:
        self._finished = False

    @property
    def truncated(self) -> bool:
        return False

    def feed(self, data: bytes) -> bytes:
        assert not self._finished
        return b""

    def finish(self) -> bytes:
        self._finished = True
        return b"substituted"


def _substitute_factory(max_bytes: int, secrets: Iterable[bytes]) -> OutputSanitizer:
    assert max_bytes > 0
    tuple(secrets)
    return _SubstituteSanitizer()


class _RejectingSanitizer:
    @property
    def truncated(self) -> bool:
        return False

    def feed(self, data: bytes) -> bytes:
        raise OutputSanitizationError("injected rejection")

    def finish(self) -> bytes:
        raise OutputSanitizationError("injected rejection")


def _rejecting_factory(max_bytes: int, secrets: Iterable[bytes]) -> OutputSanitizer:
    del max_bytes, secrets
    return _RejectingSanitizer()


async def test_process_runner_contract_returns_sanitized_artifact_refs(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    runner: ProcessRunner = AsyncioProcessRunner(
        store,
        sanitizer_factory=StreamingOutputSanitizer,
    )

    result = await runner.run(_request(executable, tmp_path))

    assert result.succeeded
    assert result.stdout_ref is not None
    assert result.stderr_ref is not None
    assert store.read(cast(ArtifactRef, result.stdout_ref)) == b"contract-argument\n"
    assert store.read(cast(ArtifactRef, result.stderr_ref)) == b""
    assert result.truncated is False
    assert os.path.commonpath([str(result.stdout_ref.relative_path), "process"]) == "process"


def test_process_runner_contract_exposes_materialization_limit(tmp_path: Path) -> None:
    reduced_limit = 1024
    policy = ProcessPolicy()

    assert policy.max_executable_bytes == DEFAULT_MAX_EXECUTABLE_BYTES
    with pytest.raises(ValueError):
        ProcessPolicy(max_executable_bytes=DEFAULT_MAX_EXECUTABLE_BYTES + 1)

    reduced = ProcessRequest(
        argv=("/bin/echo",),
        cwd=tmp_path,
        policy=ProcessPolicy(max_executable_bytes=reduced_limit),
        allowed_executables=(Path("/bin/echo"),),
        allowed_cwd_roots=(tmp_path,),
    )
    assert reduced.policy.max_executable_bytes == reduced_limit


async def test_process_runner_uses_injected_sanitizer_factory(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    runner: ProcessRunner = AsyncioProcessRunner(
        store,
        sanitizer_factory=_substitute_factory,
    )

    result = await runner.run(_request(executable, tmp_path))

    assert result.stdout_ref is not None
    assert result.stderr_ref is not None
    assert store.read(cast(ArtifactRef, result.stdout_ref)) == b"substituted"
    assert store.read(cast(ArtifactRef, result.stderr_ref)) == b"substituted"


async def test_process_runner_fails_closed_when_sanitizer_rejects(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    runner: ProcessRunner = AsyncioProcessRunner(
        store,
        sanitizer_factory=_rejecting_factory,
    )

    with pytest.raises(ProcessArtifactError):
        await runner.run(_request(executable, tmp_path))

    assert not tuple((store.root / "runs").rglob("*.bin"))
