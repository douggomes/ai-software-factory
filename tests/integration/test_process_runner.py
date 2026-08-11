"""Integration tests for the secure asyncio ProcessRunner."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path
from typing import cast

import pytest

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.core.ids import AttemptId, RunId
from ai_software_factory.core.process_models import (
    ProcessPolicy,
    ProcessRequest,
    TrustProfile,
)
from ai_software_factory.ports.artifacts import ArtifactRef
from ai_software_factory.ports.processes import ProcessIsolationError, ProcessPolicyError

_OUTPUT_LIMIT_BYTES = 64


def _fake_executable(tmp_path: Path, name: str, source: str) -> Path:
    executable = tmp_path / name
    executable.write_text(f"#!{sys.executable}\n{source}\n", encoding="utf-8")
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return executable


def _request(  # noqa: PLR0913 - mirrors the independently testable request controls
    executable: Path,
    cwd: Path,
    *,
    environment: dict[str, str] | None = None,
    environment_allowlist: frozenset[str] = frozenset(),
    timeout_seconds: float = 2,
    termination_grace_seconds: float = 0.2,
    max_output_bytes: int = 4_194_304,
    trust_profile: TrustProfile = TrustProfile.TRUSTED,
    isolation_available: bool | None = None,
) -> ProcessRequest:
    return ProcessRequest(
        argv=(str(executable),),
        cwd=cwd,
        policy=ProcessPolicy(
            allowed_executables=(executable,),
            allowed_cwd_roots=(cwd,),
            environment_allowlist=environment_allowlist,
        ),
        environment=environment or {},
        timeout_seconds=timeout_seconds,
        termination_grace_seconds=termination_grace_seconds,
        max_output_bytes=max_output_bytes,
        trust_profile=trust_profile,
        isolation_available=isolation_available,
        run_id=RunId("run-abc123def456"),
        attempt_id=AttemptId("att-abc123def456"),
    )


@pytest.mark.asyncio
async def test_arguments_are_literal_and_policy_enforced(tmp_path: Path) -> None:
    executable = _fake_executable(
        tmp_path,
        "literal.py",
        "import sys\nprint(repr(sys.argv[1:]))",
    )
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    runner = AsyncioProcessRunner(store)
    literal = "$(touch SHOULD_NOT_EXIST); `echo nope`; &&"

    request = _request(executable, tmp_path)
    request = ProcessRequest(
        argv=(str(executable), literal),
        cwd=request.cwd,
        policy=request.policy,
        environment=request.environment,
        timeout_seconds=request.timeout_seconds,
        termination_grace_seconds=request.termination_grace_seconds,
        max_output_bytes=request.max_output_bytes,
        run_id=request.run_id,
        attempt_id=request.attempt_id,
    )
    result = await runner.run(request)

    assert result.stdout_ref is not None
    assert literal.encode() in store.read(cast(ArtifactRef, result.stdout_ref))
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()

    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    outside = _fake_executable(outside_root, "outside.py", "print('bad')")
    outside_request = ProcessRequest(
        argv=(str(outside),),
        cwd=tmp_path,
        policy=request.policy,
        run_id=request.run_id,
        attempt_id=request.attempt_id,
    )
    with pytest.raises(ProcessPolicyError):
        await runner.run(outside_request)

    with pytest.raises(ProcessPolicyError):
        await runner.run(_request(executable, tmp_path / "missing-cwd"))


@pytest.mark.asyncio
async def test_timeout_kills_process_group(tmp_path: Path) -> None:
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"
    executable = _fake_executable(
        tmp_path,
        "process-tree.py",
        "import os, time\n"
        "from pathlib import Path\n"
        f"parent = Path({str(parent_pid_file)!r})\n"
        f"child = Path({str(child_pid_file)!r})\n"
        "parent.write_text(str(os.getpid()))\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    child.write_text(str(os.getpid()))\n"
        "    time.sleep(30)\n"
        "else:\n"
        "    time.sleep(30)\n",
    )
    runner = AsyncioProcessRunner()
    task = asyncio.create_task(
        runner.run(
            _request(
                executable,
                tmp_path,
                timeout_seconds=1,
                termination_grace_seconds=0.1,
            )
        )
    )

    for _ in range(200):
        if parent_pid_file.exists() and child_pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert parent_pid_file.exists()
    assert child_pid_file.exists()
    result = await task

    assert result.timed_out
    assert result.signal is not None
    parent_pid = int(parent_pid_file.read_text(encoding="utf-8"))
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    for _ in range(100):
        if not _pid_exists(parent_pid) and not _pid_exists(child_pid):
            break
        await asyncio.sleep(0.01)
    assert not _pid_exists(parent_pid)
    assert not _pid_exists(child_pid)


@pytest.mark.asyncio
async def test_cancellation_kills_process_group(tmp_path: Path) -> None:
    parent_pid_file = tmp_path / "cancel-parent.pid"
    child_pid_file = tmp_path / "cancel-child.pid"
    executable = _fake_executable(
        tmp_path,
        "cancel-tree.py",
        "import os, time\n"
        "from pathlib import Path\n"
        f"parent = Path({str(parent_pid_file)!r})\n"
        f"child = Path({str(child_pid_file)!r})\n"
        "parent.write_text(str(os.getpid()))\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    child.write_text(str(os.getpid()))\n"
        "    time.sleep(30)\n"
        "else:\n"
        "    time.sleep(30)\n",
    )
    runner = AsyncioProcessRunner()
    task = asyncio.create_task(
        runner.run(
            _request(
                executable,
                tmp_path,
                timeout_seconds=10,
                termination_grace_seconds=0.1,
            )
        )
    )

    for _ in range(200):
        if parent_pid_file.exists() and child_pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert parent_pid_file.exists()
    assert child_pid_file.exists()
    parent_pid = int(parent_pid_file.read_text(encoding="utf-8"))
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(100):
        if not _pid_exists(parent_pid) and not _pid_exists(child_pid):
            break
        await asyncio.sleep(0.01)
    assert not _pid_exists(parent_pid)
    assert not _pid_exists(child_pid)


@pytest.mark.asyncio
async def test_canary_limits_and_fail_closed(tmp_path: Path) -> None:
    canary = "AIF-CANARY-DO-NOT-LEAK"
    executable = _fake_executable(
        tmp_path,
        "flood.py",
        "import os, sys\n"
        "sys.stdout.write(os.environ['AIF_CANARY'])\n"
        "sys.stdout.write('x' * 200)\n"
        "sys.stderr.write('secret=' + os.environ['AIF_CANARY'])\n",
    )
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    runner = AsyncioProcessRunner(store)
    request = _request(
        executable,
        tmp_path,
        environment={"AIF_CANARY": canary},
        environment_allowlist=frozenset({"AIF_CANARY"}),
        max_output_bytes=_OUTPUT_LIMIT_BYTES,
    )

    result = await runner.run(request)

    assert result.truncated
    assert result.stdout_ref is not None
    assert result.stderr_ref is not None
    stdout = store.read(cast(ArtifactRef, result.stdout_ref))
    stderr = store.read(cast(ArtifactRef, result.stderr_ref))
    assert canary.encode() not in stdout + stderr
    assert len(stdout) <= _OUTPUT_LIMIT_BYTES
    assert len(stderr) <= _OUTPUT_LIMIT_BYTES
    assert b"<REDACTED>" in stdout + stderr

    untrusted = _request(
        executable,
        tmp_path,
        trust_profile=TrustProfile.UNTRUSTED,
        isolation_available=False,
    )
    with pytest.raises(ProcessIsolationError):
        await runner.run(untrusted)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
