"""Integration tests for FilesystemArtifactStore (TASK-005 AC-001/AC-002)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.core.ids import RunId
from ai_software_factory.ports.artifacts import (
    ARTIFACT_FILE_MODE,
    FACTORY_HOME_MODE,
    MAX_ARTIFACT_BYTES,
    SHA256_HEX_LENGTH,
    ArtifactAlreadyExistsError,
    ArtifactIntegrityError,
    ArtifactKind,
    ArtifactNotFoundError,
    ArtifactRef,
    ArtifactTooLargeError,
)


def _ref(run_id: str = "run-abc123def456", path: str = "plan.json") -> ArtifactRef:
    return ArtifactRef(run_id=RunId(run_id), relative_path=path, kind=ArtifactKind.PLAN)


def test_atomic_create_and_no_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-001: interrupted write leaves no published artifact; overwrite rejected."""
    home = tmp_path / "factory"
    store = FilesystemArtifactStore(home)
    assert stat.S_IMODE(home.stat().st_mode) == FACTORY_HOME_MODE

    ref = _ref()
    payload = b'{"plan":true}'
    stored = store.put(ref, payload)
    assert stored.size_bytes == len(payload)
    assert len(stored.sha256) == SHA256_HEX_LENGTH
    assert store.read(ref) == payload

    published = home / "runs" / ref.run_id.value / ref.relative_path
    assert published.is_file()
    assert not published.is_symlink()
    assert stat.S_IMODE(published.stat().st_mode) == ARTIFACT_FILE_MODE
    temps = list(published.parent.glob(".aif-tmp-*"))
    assert temps == []

    with pytest.raises(ArtifactAlreadyExistsError):
        store.put(ref, b"other")
    assert store.read(ref) == payload

    orphan = published.parent / ".aif-tmp-orphan"
    orphan.write_bytes(b"partial")
    os.chmod(orphan, ARTIFACT_FILE_MODE)
    assert store.read(ref) == payload
    assert orphan.exists()
    with pytest.raises(ValueError):
        ArtifactRef(run_id=ref.run_id, relative_path=".aif-tmp-orphan", kind=ArtifactKind.OTHER)
    with pytest.raises(ValueError):
        ArtifactRef(run_id=ref.run_id, relative_path="../escape", kind=ArtifactKind.OTHER)

    original_write = os.write

    def interrupted_write(fd: int, data: bytes) -> int:
        original_write(fd, data[:1])
        raise OSError("simulated interruption")

    interrupted_ref = _ref(path="interrupted.bin")
    monkeypatch.setattr(os, "write", interrupted_write)
    with pytest.raises(ArtifactIntegrityError):
        store.put(interrupted_ref, b"partial")
    interrupted_path = home / "runs" / interrupted_ref.run_id.value / interrupted_ref.relative_path
    assert not interrupted_path.exists()
    assert list(interrupted_path.parent.glob(".aif-tmp-*")) == [orphan]


def test_rejects_symlink_and_tampered_artifact(tmp_path: Path) -> None:
    """AC-002: symlink, external path, bad mode/owner and hash tamper fail closed."""
    home = tmp_path / "factory"
    store = FilesystemArtifactStore(home)
    ref = _ref(path="validations/gate.txt")
    original = b"gate-ok"
    store.put(ref, original)
    published = home / "runs" / ref.run_id.value / "validations" / "gate.txt"

    os.chmod(published, 0o600)
    published.write_bytes(b"gate-no")
    os.chmod(published, ARTIFACT_FILE_MODE)
    with pytest.raises(ArtifactIntegrityError):
        store.read(ref)

    home2 = tmp_path / "factory2"
    store2 = FilesystemArtifactStore(home2)
    ref2 = _ref(run_id="run-xyzxyzxyzxyz", path="spec.md")
    store2.put(ref2, b"# spec\n")
    target = home2 / "runs" / ref2.run_id.value / "spec.md"
    outside = tmp_path / "outside-secret.txt"
    outside.write_bytes(b"secret")
    os.chmod(outside, 0o600)
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ArtifactIntegrityError):
        store2.read(ref2)

    with pytest.raises(ValueError):
        ArtifactRef(run_id=RunId("run-abc123def456"), relative_path="../etc/passwd")
    with pytest.raises(ValueError):
        ArtifactRef(run_id=RunId("run-abc123def456"), relative_path="/etc/passwd")

    home3 = tmp_path / "factory3"
    store3 = FilesystemArtifactStore(home3)
    ref3 = _ref(run_id="run-modemodemode", path="mode.bin")
    store3.put(ref3, b"\x00\x01")
    path3 = home3 / "runs" / ref3.run_id.value / "mode.bin"
    os.chmod(path3, 0o644)
    with pytest.raises(ArtifactIntegrityError):
        store3.read(ref3)

    with pytest.raises(ArtifactNotFoundError):
        store3.read(_ref(run_id="run-modemodemode", path="missing.bin"))

    with pytest.raises(ArtifactTooLargeError):
        store3.put(
            _ref(run_id="run-modemodemode", path="huge.bin"),
            b"x" * (MAX_ARTIFACT_BYTES + 1),
        )


def test_rejects_symlinked_parent_missing_metadata_and_insecure_root(tmp_path: Path) -> None:
    home = tmp_path / "factory"
    store = FilesystemArtifactStore(home)
    ref = _ref(path="nested/artifact.bin")
    store.put(ref, b"payload")

    metadata = next((home / ".artifact-meta").glob("*.json"))
    metadata.unlink()
    with pytest.raises(ArtifactIntegrityError):
        store.read(ref)

    symlink_home = tmp_path / "symlink-home"
    symlink_store = FilesystemArtifactStore(symlink_home)
    outside = tmp_path / "outside"
    outside.mkdir()
    (symlink_store.root / "runs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactIntegrityError):
        symlink_store.put(_ref(run_id="run-aaaaaaaaaaab"), b"blocked")

    secure_home = tmp_path / "secure-home"
    secure_store = FilesystemArtifactStore(secure_home)
    secure_ref = _ref(run_id="run-rootmode0001")
    secure_store.put(secure_ref, b"payload")
    os.chmod(secure_home, 0o755)  # noqa: S103 - deliberate insecure-mode regression
    with pytest.raises(ArtifactIntegrityError):
        secure_store.read(secure_ref)


def test_put_creates_0700_parents(tmp_path: Path) -> None:
    home = tmp_path / "nested-home"
    store = FilesystemArtifactStore(home)
    ref = _ref(path="checkpoints/deep/file.dat")
    store.put(ref, b"data")
    runs = home / "runs"
    assert stat.S_IMODE(runs.stat().st_mode) == FACTORY_HOME_MODE
    deep = home / "runs" / ref.run_id.value / "checkpoints" / "deep"
    assert stat.S_IMODE(deep.stat().st_mode) == FACTORY_HOME_MODE
