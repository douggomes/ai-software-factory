"""Contract suite for ArtifactStore implementations."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.core.ids import RunId
from ai_software_factory.ports.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactKind,
    ArtifactNotFoundError,
    ArtifactRef,
    ArtifactStore,
)


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    return FilesystemArtifactStore(tmp_path / "home")


def _ref(name: str = "blob.bin") -> ArtifactRef:
    return ArtifactRef(
        run_id=RunId("run-contract0001"),
        relative_path=name,
        kind=ArtifactKind.OTHER,
    )


def test_put_then_read_roundtrip(artifact_store: ArtifactStore) -> None:
    ref = _ref()
    data = b"hello-artifact"
    stored = artifact_store.put(ref, data)
    assert stored.ref == ref
    assert stored.size_bytes == len(data)
    assert artifact_store.read(ref) == data


def test_put_rejects_overwrite(artifact_store: ArtifactStore) -> None:
    ref = _ref("once.txt")
    artifact_store.put(ref, b"v1")
    with pytest.raises(ArtifactAlreadyExistsError):
        artifact_store.put(ref, b"v2")
    assert artifact_store.read(ref) == b"v1"


def test_read_missing_raises(artifact_store: ArtifactStore) -> None:
    with pytest.raises(ArtifactNotFoundError):
        artifact_store.read(_ref("missing.txt"))
