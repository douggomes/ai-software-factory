"""Integration coverage for bounded cross-chunk output sanitization."""

from __future__ import annotations

import stat
import sys
from pathlib import Path
from typing import cast

import pytest

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.core.ids import AttemptId, RunId
from ai_software_factory.core.process_models import ProcessPolicy, ProcessRequest
from ai_software_factory.ports.artifacts import ArtifactRef
from ai_software_factory.ports.output_sanitization import OutputSanitizationError

_OUTPUT_LIMIT = 256
_EXPECTED_REDACTIONS = 6


def _fake_executable(path: Path, chunks: tuple[str, ...]) -> Path:
    executable = path / "hostile-output.py"
    source = (
        f"#!{sys.executable}\n"
        "import os\n"
        f"chunks = {chunks!r}\n"
        "for chunk in chunks:\n"
        "    os.write(1, chunk.encode())\n"
        "    os.write(2, chunk.encode())\n"
    )
    executable.write_text(source, encoding="utf-8")
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return executable


@pytest.mark.asyncio
async def test_streaming_sanitizer_redacts_structured_and_split_secrets(
    tmp_path: Path,
) -> None:
    canary = "CANARY" + "-VALUE-DO-NOT-PERSIST"
    cloud_token = "AKIA" + "A" * 16
    private_key = (
        "-----BEGIN " + "PRIVATE KEY-----\n" + "sensitive-material\n" + "-----END PRIVATE KEY-----"
    )
    json_value = "JSON-" + "CREDENTIAL WITH SPACES"
    quoted_value = "short " + "credential"
    mapping_value = "python mapping " + "credential"
    chunks = (
        "prefix token=" + canary[:8],
        canary[8:] + "\n" + private_key[:19],
        private_key[19:] + "\n" + cloud_token[:7],
        cloud_token[7:] + '\n{"token":"' + json_value[:8],
        json_value[8:]
        + "\"}\npassword='"
        + quoted_value
        + "'\n{'token': '"
        + mapping_value
        + "'}\nsuffix\n"
        + "x" * 512,
    )
    sanitizer = StreamingOutputSanitizer(_OUTPUT_LIMIT, (canary.encode(),))
    for chunk in chunks:
        assert sanitizer.feed(chunk.encode()) == b""
    sanitized = sanitizer.finish()

    assert sanitizer.truncated
    assert len(sanitized) <= _OUTPUT_LIMIT
    assert canary.encode() not in sanitized
    assert cloud_token.encode() not in sanitized
    assert b"sensitive-material" not in sanitized
    assert json_value.encode() not in sanitized
    assert quoted_value.encode() not in sanitized
    assert mapping_value.encode() not in sanitized
    assert sanitized.count(b"<REDACTED>") >= _EXPECTED_REDACTIONS
    with pytest.raises(OutputSanitizationError):
        StreamingOutputSanitizer(8, (b"explicit-secret-too-long",))
    large_limit = 8192
    long_explicit = b"S" * large_limit
    boundary = StreamingOutputSanitizer(large_limit, (long_explicit,))
    boundary.feed(b"x" * (large_limit - 1) + long_explicit)
    boundary_output = boundary.finish()
    assert long_explicit not in boundary_output
    assert b"S" not in boundary_output

    executable = _fake_executable(tmp_path, chunks)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    runner = AsyncioProcessRunner(store, sanitizer_factory=StreamingOutputSanitizer)
    result = await runner.run(
        ProcessRequest(
            argv=(str(executable),),
            executable=executable,
            cwd=tmp_path,
            policy=ProcessPolicy(
                allowed_executables=(executable,),
                allowed_cwd_roots=(tmp_path,),
            ),
            redaction_secrets=(canary,),
            max_output_bytes=_OUTPUT_LIMIT,
            run_id=RunId("run-abc123def456"),
            attempt_id=AttemptId("att-abc123def456"),
        )
    )

    assert result.truncated
    assert result.stdout_ref is not None
    assert result.stderr_ref is not None
    artifacts = (
        store.read(cast(ArtifactRef, result.stdout_ref)),
        store.read(cast(ArtifactRef, result.stderr_ref)),
    )
    for artifact in artifacts:
        assert artifact == sanitized
        assert canary.encode() not in artifact
        assert cloud_token.encode() not in artifact
        assert b"sensitive-material" not in artifact
        assert json_value.encode() not in artifact
        assert quoted_value.encode() not in artifact
        assert mapping_value.encode() not in artifact
