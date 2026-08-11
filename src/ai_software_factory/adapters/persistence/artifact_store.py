"""Filesystem ArtifactStore and the SQLite event projection adapter.

Artifact writes use a temporary file in the destination directory, ``fsync``
and an atomic hard-link publication. A hard link gives the create-exclusive
semantics required by the port: an existing artifact can never be replaced.
Reads refuse symlinks, validate the opened file descriptor and recompute the
recorded SHA-256 digest before returning bytes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import uuid
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ai_software_factory.adapters.persistence.schema import events_table
from ai_software_factory.adapters.persistence.sqlite import BUSY_TIMEOUT_MS
from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import AttemptId, RunId, TaskId
from ai_software_factory.ports.artifacts import (
    ARTIFACT_FILE_MODE,
    FACTORY_HOME_MODE,
    HASH_ALGORITHM,
    MAX_ARTIFACT_BYTES,
    ArtifactAlreadyExistsError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactRef,
    ArtifactStore,
    ArtifactTooLargeError,
    StoredArtifact,
)

_TEMP_PREFIX: Final[str] = ".aif-tmp-"
_RUNS_DIRNAME: Final[str] = "runs"
_METADATA_DIRNAME: Final[str] = ".artifact-meta"
_METADATA_FILE_MODE: Final[int] = 0o600
_MAX_METADATA_BYTES: Final[int] = 16_384


def _sha256_hex(data: bytes) -> str:
    return hashlib.new(HASH_ALGORITHM, data).hexdigest()


def _decode_json_object(raw: str, context: str) -> dict[str, object]:
    try:
        loaded: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactIntegrityError(f"corrupt {context}") from error
    if not isinstance(loaded, dict):
        raise ArtifactIntegrityError(f"corrupt {context}")
    untyped_payload = cast(dict[object, object], loaded)
    payload: dict[str, object] = {}
    for key, value in untyped_payload.items():
        if not isinstance(key, str):
            raise ArtifactIntegrityError(f"corrupt {context}")
        payload[key] = value
    return payload


class FilesystemArtifactStore:
    """ArtifactStore rooted at a factory home directory (``0700``)."""

    def __init__(self, factory_home: Path) -> None:
        requested_root = factory_home.expanduser()
        if requested_root.is_symlink():
            raise ArtifactIntegrityError("factory home must not be a symlink")
        self._root = requested_root.resolve(strict=False)
        if not self._root.exists():
            self._root.mkdir(parents=True, exist_ok=True)
        self._ensure_directory(self._root, FACTORY_HOME_MODE, create=False)
        self._meta_dir = self._root / _METADATA_DIRNAME
        self._ensure_directory(self._meta_dir, FACTORY_HOME_MODE, create=True)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, ref: ArtifactRef, data: bytes) -> StoredArtifact:
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ArtifactTooLargeError(len(data))
        dest = self._resolve_dest(ref)
        self._reject_existing_destination(dest, ref)
        self._ensure_directory_tree(dest.parent)
        self._reject_existing_destination(dest, ref)
        digest = _sha256_hex(data)
        temp_path = dest.parent / f"{_TEMP_PREFIX}{uuid.uuid4().hex}"
        try:
            self._write_exclusive_temp(temp_path, data)
            try:
                os.link(temp_path, dest)
            except FileExistsError as error:
                raise ArtifactAlreadyExistsError(ref) from error
            except OSError as error:
                raise ArtifactIntegrityError(
                    f"failed to publish artifact {ref.relative_path}: {error}"
                ) from error
        finally:
            with contextlib.suppress(OSError):
                temp_path.unlink()
        stored = StoredArtifact(ref=ref, sha256=digest, size_bytes=len(data))
        self._assert_safe_file(dest, ref)
        self._write_metadata(stored)
        return stored

    def read(self, ref: ArtifactRef) -> bytes:
        dest = self._resolve_dest(ref)
        self._assert_safe_file(dest, ref)
        expected = self._read_metadata(ref)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(dest, flags)
        except OSError as error:
            raise ArtifactIntegrityError(
                f"cannot open artifact {ref.relative_path}: {error}"
            ) from error
        try:
            file_stat = os.fstat(fd)
            self._validate_artifact_stat(file_stat, ref)
            data = self._read_limited(fd, MAX_ARTIFACT_BYTES, ref.relative_path)
        finally:
            os.close(fd)
        if len(data) != file_stat.st_size:
            raise ArtifactIntegrityError(
                f"size changed while reading {ref.relative_path}: "
                f"expected {file_stat.st_size}, got {len(data)}"
            )
        if len(data) != expected.size_bytes:
            raise ArtifactIntegrityError(
                f"size mismatch for {ref.relative_path}: "
                f"expected {expected.size_bytes}, got {len(data)}"
            )
        digest = _sha256_hex(data)
        if digest != expected.sha256:
            raise ArtifactIntegrityError(
                f"hash mismatch for {ref.relative_path}: expected {expected.sha256}, got {digest}"
            )
        return data

    def _write_exclusive_temp(self, temp_path: Path, data: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(temp_path, flags, ARTIFACT_FILE_MODE)
        except OSError as error:
            raise ArtifactIntegrityError(f"cannot create temp artifact: {error}") from error
        try:
            self._write_all(fd, data, "artifact")
            os.fsync(fd)
            os.chmod(temp_path, ARTIFACT_FILE_MODE)
        except OSError as error:
            with contextlib.suppress(OSError):
                temp_path.unlink()
            raise ArtifactIntegrityError(f"failed writing temp artifact: {error}") from error
        finally:
            os.close(fd)

    def _resolve_dest(self, ref: ArtifactRef) -> Path:
        relative = Path(_RUNS_DIRNAME) / ref.run_id.value / Path(ref.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ArtifactIntegrityError(f"path escapes artifact root: {ref.relative_path}")
        candidate = self._root / relative
        self._assert_no_symlinked_parents(candidate)
        try:
            candidate.relative_to(self._root)
        except ValueError as error:
            raise ArtifactIntegrityError(
                f"path escapes artifact root: {ref.relative_path}"
            ) from error
        return candidate

    def _ensure_directory_tree(self, directory: Path) -> None:
        relative = directory.relative_to(self._root)
        current = self._root
        for part in relative.parts:
            current = current / part
            self._ensure_directory(current, FACTORY_HOME_MODE, create=True)

    def _ensure_directory(self, directory: Path, mode: int, *, create: bool) -> None:
        try:
            directory_stat = os.lstat(directory)
        except FileNotFoundError:
            if not create:
                raise ArtifactIntegrityError(f"directory is missing: {directory}") from None
            try:
                os.mkdir(directory, mode)
            except OSError as error:
                raise ArtifactIntegrityError(
                    f"cannot create directory {directory}: {error}"
                ) from error
            directory_stat = os.lstat(directory)
        except OSError as error:
            raise ArtifactIntegrityError(
                f"cannot inspect directory {directory}: {error}"
            ) from error
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            raise ArtifactIntegrityError(f"directory is not a real directory: {directory}")
        if directory_stat.st_uid != os.getuid():
            raise ArtifactIntegrityError(f"directory owner mismatch: {directory}")
        try:
            os.chmod(directory, mode)
        except OSError as error:
            raise ArtifactIntegrityError(f"cannot secure directory {directory}: {error}") from error

    def _assert_no_symlinked_parents(self, path: Path) -> None:
        relative = path.relative_to(self._root)
        current = self._root
        parts = relative.parts
        for index, part in enumerate(parts):
            current = current / part
            try:
                current_stat = os.lstat(current)
            except FileNotFoundError:
                break
            except OSError as error:
                raise ArtifactIntegrityError(
                    f"cannot inspect artifact path {current}: {error}"
                ) from error
            if stat.S_ISLNK(current_stat.st_mode):
                raise ArtifactIntegrityError(f"symlink in artifact path: {current}")
            if index < len(parts) - 1 and not stat.S_ISDIR(current_stat.st_mode):
                raise ArtifactIntegrityError(
                    f"artifact path component is not a directory: {current}"
                )

    def _reject_existing_destination(self, dest: Path, ref: ArtifactRef) -> None:
        try:
            destination_stat = os.lstat(dest)
        except FileNotFoundError:
            return
        except OSError as error:
            raise ArtifactIntegrityError(f"cannot inspect artifact path {dest}: {error}") from error
        if stat.S_ISLNK(destination_stat.st_mode):
            raise ArtifactIntegrityError(f"symlink refused: {ref.relative_path}")
        if not stat.S_ISREG(destination_stat.st_mode):
            raise ArtifactIntegrityError(f"artifact destination is not a file: {ref.relative_path}")
        raise ArtifactAlreadyExistsError(ref)

    def _assert_safe_root(self) -> None:
        self._assert_secure_directory(self._root, FACTORY_HOME_MODE)

    def _assert_secure_directory(self, directory: Path, mode: int) -> None:
        try:
            directory_stat = os.lstat(directory)
        except FileNotFoundError as error:
            raise ArtifactIntegrityError(f"directory is missing: {directory}") from error
        except OSError as error:
            raise ArtifactIntegrityError(
                f"cannot inspect directory {directory}: {error}"
            ) from error
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            raise ArtifactIntegrityError(f"directory is not a real directory: {directory}")
        if directory_stat.st_uid != os.getuid():
            raise ArtifactIntegrityError(f"directory owner mismatch: {directory}")
        if stat.S_IMODE(directory_stat.st_mode) != mode:
            raise ArtifactIntegrityError(
                f"directory mode mismatch for {directory}: expected {oct(mode)}"
            )

    def _assert_safe_file(self, dest: Path, ref: ArtifactRef) -> os.stat_result:
        self._assert_safe_root()
        try:
            file_stat = os.lstat(dest)
        except FileNotFoundError as error:
            raise ArtifactNotFoundError(ref) from error
        except OSError as error:
            raise ArtifactIntegrityError(
                f"cannot stat artifact {ref.relative_path}: {error}"
            ) from error
        if stat.S_ISLNK(file_stat.st_mode):
            raise ArtifactIntegrityError(f"symlink refused: {ref.relative_path}")
        if not stat.S_ISREG(file_stat.st_mode):
            raise ArtifactIntegrityError(f"not a regular file: {ref.relative_path}")
        self._validate_artifact_stat(file_stat, ref)
        return file_stat

    def _validate_artifact_stat(self, file_stat: os.stat_result, ref: ArtifactRef) -> None:
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise ArtifactIntegrityError(
                f"artifact changed to a non-regular file: {ref.relative_path}"
            )
        if file_stat.st_uid != os.getuid():
            raise ArtifactIntegrityError(f"owner changed while reading {ref.relative_path}")
        if stat.S_IMODE(file_stat.st_mode) != ARTIFACT_FILE_MODE:
            raise ArtifactIntegrityError(f"mode changed while reading {ref.relative_path}")
        if file_stat.st_size > MAX_ARTIFACT_BYTES:
            raise ArtifactTooLargeError(file_stat.st_size)

    def _write_all(self, fd: int, data: bytes, description: str) -> None:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(f"short write while creating {description}")
            view = view[written:]

    def _read_limited(self, fd: int, limit: int, description: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            chunk = os.read(fd, limit + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > limit:
            raise ArtifactTooLargeError(total)
        return b"".join(chunks)

    def _metadata_path(self, ref: ArtifactRef) -> Path:
        key = _sha256_hex(f"{ref.run_id.value}/{ref.relative_path}".encode())
        return self._meta_dir / f"{key}.json"

    def _write_metadata(self, stored: StoredArtifact) -> None:
        self._ensure_directory(self._meta_dir, FACTORY_HOME_MODE, create=False)
        path = self._metadata_path(stored.ref)
        payload = {
            "run_id": stored.ref.run_id.value,
            "relative_path": stored.ref.relative_path,
            "kind": stored.ref.kind.name,
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
        }
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        temp = path.with_name(f"{_TEMP_PREFIX}{uuid.uuid4().hex}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(temp, flags, _METADATA_FILE_MODE)
        except OSError as error:
            raise ArtifactIntegrityError(f"cannot create artifact metadata: {error}") from error
        try:
            self._write_all(fd, encoded, "artifact metadata")
            os.fsync(fd)
            os.chmod(temp, _METADATA_FILE_MODE)
            try:
                os.link(temp, path)
            except FileExistsError as error:
                raise ArtifactIntegrityError(
                    f"artifact metadata already exists for {stored.ref.relative_path}"
                ) from error
            except OSError as error:
                raise ArtifactIntegrityError(
                    f"cannot publish artifact metadata: {error}"
                ) from error
        except OSError as error:
            raise ArtifactIntegrityError(f"failed writing artifact metadata: {error}") from error
        finally:
            os.close(fd)
            with contextlib.suppress(OSError):
                temp.unlink()

    def _read_metadata(self, ref: ArtifactRef) -> StoredArtifact:
        self._assert_secure_directory(self._meta_dir, FACTORY_HOME_MODE)
        path = self._metadata_path(ref)
        metadata_stat = self._stat_metadata(path, ref)
        raw = self._read_metadata_bytes(path, ref)
        payload = _decode_json_object(
            raw.decode("utf-8"), f"artifact metadata for {ref.relative_path}"
        )
        self._validate_metadata_reference(payload, ref, metadata_stat)
        sha = payload.get("sha256")
        size = payload.get("size_bytes")
        if not isinstance(sha, str) or type(size) is not int:
            raise ArtifactIntegrityError(f"corrupt artifact metadata for {ref.relative_path}")
        try:
            return StoredArtifact(ref=ref, sha256=sha, size_bytes=size)
        except ValueError as error:
            raise ArtifactIntegrityError(
                f"corrupt artifact metadata for {ref.relative_path}"
            ) from error

    def _stat_metadata(self, path: Path, ref: ArtifactRef) -> os.stat_result:
        try:
            metadata_stat = os.lstat(path)
        except FileNotFoundError as error:
            raise ArtifactIntegrityError(
                f"missing artifact metadata for {ref.relative_path}"
            ) from error
        except OSError as error:
            raise ArtifactIntegrityError(f"cannot inspect artifact metadata: {error}") from error
        if stat.S_ISLNK(metadata_stat.st_mode) or not stat.S_ISREG(metadata_stat.st_mode):
            raise ArtifactIntegrityError(f"invalid artifact metadata path for {ref.relative_path}")
        if metadata_stat.st_uid != os.getuid():
            raise ArtifactIntegrityError(
                f"artifact metadata owner mismatch for {ref.relative_path}"
            )
        if stat.S_IMODE(metadata_stat.st_mode) != _METADATA_FILE_MODE:
            raise ArtifactIntegrityError(f"invalid artifact metadata mode for {ref.relative_path}")
        if metadata_stat.st_size > _MAX_METADATA_BYTES:
            raise ArtifactIntegrityError(f"artifact metadata is too large for {ref.relative_path}")
        return metadata_stat

    def _read_metadata_bytes(self, path: Path, ref: ArtifactRef) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
        except OSError as error:
            raise ArtifactIntegrityError(f"cannot open artifact metadata: {error}") from error
        try:
            raw = self._read_limited(fd, _MAX_METADATA_BYTES, ref.relative_path)
        finally:
            os.close(fd)
        return raw

    def _validate_metadata_reference(
        self,
        payload: dict[str, object],
        ref: ArtifactRef,
        metadata_stat: os.stat_result,
    ) -> None:
        if payload.get("run_id") != ref.run_id.value:
            raise ArtifactIntegrityError(f"artifact metadata run mismatch for {ref.relative_path}")
        if payload.get("relative_path") != ref.relative_path:
            raise ArtifactIntegrityError(f"artifact metadata path mismatch for {ref.relative_path}")
        if payload.get("kind") != ref.kind.name:
            raise ArtifactIntegrityError(f"artifact metadata kind mismatch for {ref.relative_path}")
        if metadata_stat.st_size == 0:
            raise ArtifactIntegrityError(f"empty artifact metadata for {ref.relative_path}")


class SqliteEventLogReader:
    """Read-only event projection from the SQLite ledger."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    async def connect(cls, db_path: Path) -> SqliteEventLogReader:
        connection_string = f"sqlite+aiosqlite:///{db_path}"
        engine = create_async_engine(
            connection_string,
            echo=False,
            connect_args={"timeout": BUSY_TIMEOUT_MS / 1000},
        )
        reader = cls(engine)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
                )
                if result.first() is None:
                    raise FileNotFoundError(f"events table missing in {db_path}")
        except BaseException:
            await engine.dispose()
            raise
        return reader

    async def list_events(self, run_id: RunId) -> tuple[DomainEvent, ...]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(events_table)
                .where(events_table.c.run_id == run_id.value)
                .order_by(events_table.c.event_id.asc())
            )
            rows = result.fetchall()
        events: list[DomainEvent] = []
        for row in rows:
            payload_raw = row.payload
            payload: dict[str, object] | None
            if payload_raw is None:
                payload = None
            else:
                payload = _decode_json_object(payload_raw, f"event payload for run {run_id.value}")
            timestamp = row.timestamp
            if not isinstance(timestamp, datetime):
                raise ArtifactIntegrityError(
                    f"event timestamp is not datetime for run {run_id.value}"
                )
            events.append(
                DomainEvent(
                    event_type=EventType[row.event_type],
                    timestamp=timestamp,
                    run_id=RunId(row.run_id),
                    task_id=TaskId(row.task_id) if row.task_id else None,
                    attempt_id=AttemptId(row.attempt_id) if row.attempt_id else None,
                    payload=payload,
                    schema_version=int(row.schema_version),
                )
            )
        return tuple(events)

    async def close(self) -> None:
        await self._engine.dispose()


def ensure_artifact_store(factory_home: Path) -> ArtifactStore:
    """Composition helper: construct the filesystem ArtifactStore."""
    return FilesystemArtifactStore(factory_home)
