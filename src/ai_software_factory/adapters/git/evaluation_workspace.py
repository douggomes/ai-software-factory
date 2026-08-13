"""Safe Git inventory and private evaluation snapshot adapter."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, cast

from ai_software_factory.core.evaluation_workspace import (
    DEFAULT_MAX_EVALUATION_FILES,
    EvaluationCaptureRequest,
    EvaluationSnapshot,
    FileClassification,
    ManifestEntry,
    RepositoryEvidence,
    SecretFinding,
    SnapshotLifecycle,
    detect_secrets,
)
from ai_software_factory.core.ids import AttemptId
from ai_software_factory.core.process_models import ProcessPolicy, ProcessRequest, TrustProfile
from ai_software_factory.core.workspace_models import Workspace
from ai_software_factory.ports.artifacts import (
    ArtifactError,
    ArtifactKind,
    ArtifactRef,
    ArtifactStore,
)
from ai_software_factory.ports.evaluation_workspace import (
    EvaluationWorkspace,
    EvaluationWorkspaceArtifactError,
    EvaluationWorkspaceChangedError,
    EvaluationWorkspaceCommandError,
    EvaluationWorkspacePolicyError,
    RepositoryInspection,
    WorkspaceLockCapability,
    WorkspaceLockLease,
)
from ai_software_factory.ports.processes import ProcessExecutionError, ProcessRunner

_DIRECTORY_MODE: Final[int] = 0o700
_READ_ONLY_DIRECTORY_MODE: Final[int] = 0o500
_READ_ONLY_FILE_MODE: Final[int] = 0o400
_LOCK_FILE_MODE: Final[int] = 0o600
_COPY_CHUNK_BYTES: Final[int] = 65_536
_SECRET_SCAN_OVERLAP: Final[int] = 4096
_HOOKS_CONFIG: Final[str] = "core.hooksPath=/dev/null"
_WORKTREES_DIR: Final[str] = "worktrees"
_EVALUATIONS_DIR: Final[str] = "evaluations"
_EMPTY_SHA256: Final[str] = hashlib.sha256(b"").hexdigest()
_SNAPSHOT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^snap-[0-9a-f]{12}$")
_MAX_GIT_LINK_BYTES: Final[int] = 4096
_MAX_GIT_INDEX_BYTES: Final[int] = 268_435_456
_MAX_INVENTORY_DEPTH: Final[int] = 128
_MAX_INVENTORY_PATH_BYTES: Final[int] = 67_108_864
_MAX_SECRET_FINDINGS: Final[int] = 100_000
_MAX_SECRET_EVIDENCE_BYTES: Final[int] = 16_777_216
_CREDENTIAL_NAMES: Final[frozenset[str]] = frozenset(
    {".env", ".npmrc", ".netrc", "auth.json", "credentials", "credentials.json"}
)
_CREDENTIAL_SUFFIXES: Final[tuple[str, ...]] = (".pem", ".key", ".p12", ".pfx")


@dataclass(frozen=True, slots=True)
class _GitState:
    head_commit: str
    tracked: tuple[str, ...]
    untracked: tuple[str, ...]
    ignored: tuple[str, ...]
    changed_tracked: tuple[str, ...]

    @property
    def signature(self) -> str:
        payload = json.dumps(
            {
                "head": self.head_commit,
                "tracked": self.tracked,
                "untracked": self.untracked,
                "ignored": self.ignored,
                "changed_tracked": self.changed_tracked,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _SourceContent:
    size_bytes: int
    sha256: str
    binary: bool
    stat_identity: tuple[int, int, int, int, int]
    findings: tuple[SecretFinding, ...]
    diff_check_failed: bool


@dataclass(frozen=True, slots=True)
class _GitControl:
    root: Path
    root_fd: int
    root_identity: tuple[int, int]
    source_fd: int
    source_identity: tuple[int, int]
    source_hashes: tuple[tuple[str, str], ...]
    common_fd: int
    common_identity: tuple[int, int]
    common_hashes: tuple[tuple[str, str], ...]
    common_absent: tuple[str, ...]
    private_hashes: tuple[tuple[str, str], ...]


class GitEvaluationWorkspace(EvaluationWorkspace, RepositoryInspection):
    """Capture and verify one bounded snapshot without executing repository code."""

    def __init__(
        self,
        process_runner: ProcessRunner,
        artifact_store: ArtifactStore,
        git_executable: Path,
        lock_capability: WorkspaceLockCapability,
        snapshot_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._process_runner = process_runner
        self._artifact_store = artifact_store
        self._git_executable = Path(git_executable)
        self._lock_capability = lock_capability
        self._snapshot_id_factory = snapshot_id_factory or (lambda: f"snap-{uuid.uuid4().hex[:12]}")

    async def capture(self, request: EvaluationCaptureRequest) -> EvaluationSnapshot:
        """Publish a read-only snapshot only after source and Git state agree twice."""
        workspace = _authorize_workspace(request.workspace)
        snapshot_id = _create_snapshot_id(self._snapshot_id_factory)
        staging = final_root = _snapshot_root(workspace, snapshot_id)
        completed = False
        final_created = False
        lock_lease = _borrow_lock_lease(self._lock_capability, workspace)
        try:
            _assert_lock_lease_active(lock_lease)
            source_fd = _open_directory(workspace.worktree_path)
            source_identity = _directory_identity(os.fstat(source_fd))
            try:
                git_directory = _verify_git_and_source_identity(
                    source_fd, workspace, source_identity
                )
                with _private_git_control(workspace, git_directory) as git_control:
                    before = await self._git_state(workspace, source_identity, git_control)
                    diff_check_failed = await self._git_diff_check(workspace, git_control)
                    classifications = _classifications(before, request.max_files)
                    staging, final_root = _prepare_staging(workspace, snapshot_id)
                    entries, findings, content_diff_check_failed = _materialize(
                        source_fd,
                        staging,
                        classifications,
                        request.max_total_bytes,
                        frozenset(
                            set(before.changed_tracked)
                            | set(before.untracked)
                            | set(before.ignored)
                        ),
                    )
                    _verify_stable_git_state(
                        source_fd,
                        workspace,
                        entries,
                        (
                            before,
                            await self._git_state(workspace, source_identity, git_control),
                        ),
                        git_control,
                    )
                    _verify_source(source_fd, entries)
                    manifest_hash_seed = _entries_hash(entries)
                    diff_hash = _diff_hash(before, manifest_hash_seed)
                    evidence = _evidence(
                        before,
                        entries,
                        findings,
                        diff_hash,
                        diff_check_failed or content_diff_check_failed,
                    )
                    manifest_bytes = _manifest_bytes(
                        snapshot_id,
                        workspace,
                        before.head_commit,
                        entries,
                        evidence,
                    )
                    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
                    identity_hash = _identity_hash(
                        snapshot_id,
                        workspace,
                        before.head_commit,
                        diff_hash,
                        manifest_hash,
                    )
                    _publish_staging(staging, final_root.parent)
                    final_created = True
                    _make_read_only(final_root.parent)
                    manifest_ref = ArtifactRef(
                        run_id=workspace.run_id,
                        relative_path=f"evaluations/{snapshot_id}/manifest.json",
                        kind=ArtifactKind.VALIDATION,
                    )
                    snapshot = EvaluationSnapshot(
                        snapshot_id=snapshot_id,
                        workspace=workspace,
                        root=final_root,
                        head_commit=before.head_commit,
                        entries=entries,
                        evidence=evidence,
                        manifest_ref=manifest_ref,
                        manifest_hash=manifest_hash,
                        identity_hash=identity_hash,
                        lifecycle=SnapshotLifecycle.VERIFIED,
                    )
                    _verify_snapshot_files(final_root, entries)
                    _verify_final_source(
                        source_fd,
                        workspace,
                        source_identity,
                        entries,
                        request.max_files,
                    )
                    _verify_git_control(git_control)
                    _assert_lock_lease_active(lock_lease)
                _assert_lock_lease_active(lock_lease)
                _store_manifest(self._artifact_store, manifest_ref, manifest_bytes)
                completed = True
                return snapshot
            finally:
                os.close(source_fd)
                if not completed:
                    _remove_owned_staging(staging)
                    if final_created:
                        _remove_owned_snapshot(final_root.parent, workspace, snapshot_id)
        finally:
            lock_lease.close()

    async def verify_source_current(self, snapshot: EvaluationSnapshot) -> None:
        """Prove that a source remained identical for a completed evaluation."""
        workspace = _authorize_workspace(snapshot.workspace)
        self.inspect(snapshot)
        lock_lease = _borrow_lock_lease(self._lock_capability, workspace)
        try:
            _assert_lock_lease_active(lock_lease)
            source_fd = _open_directory(workspace.worktree_path)
            source_identity = _directory_identity(os.fstat(source_fd))
            try:
                git_directory = _verify_git_and_source_identity(
                    source_fd, workspace, source_identity
                )
                with _private_git_control(workspace, git_directory) as git_control:
                    state = await self._git_state(workspace, source_identity, git_control)
                    expected_classifications = tuple(
                        (entry.path, entry.classification) for entry in snapshot.entries
                    )
                    if _classifications(state, len(snapshot.entries)) != expected_classifications:
                        raise EvaluationWorkspaceChangedError(
                            "workspace classification changed during evaluation"
                        )
                    _verify_source(source_fd, snapshot.entries)
                    _verify_final_source(
                        source_fd,
                        workspace,
                        source_identity,
                        snapshot.entries,
                        DEFAULT_MAX_EVALUATION_FILES,
                    )
                    if (
                        _diff_hash(state, _entries_hash(snapshot.entries))
                        != snapshot.evidence.diff_hash
                    ):
                        raise EvaluationWorkspaceChangedError(
                            "workspace Git state changed during evaluation"
                        )
                    _verify_git_control(git_control)
                    _assert_lock_lease_active(lock_lease)
            finally:
                os.close(source_fd)
        finally:
            lock_lease.close()

    def inspect(self, snapshot: EvaluationSnapshot) -> RepositoryEvidence:
        """Verify artifact, root identity and every included file before use."""
        workspace = _authorize_workspace(snapshot.workspace)
        expected_root = _snapshot_root(workspace, snapshot.snapshot_id)
        if snapshot.root != expected_root:
            raise EvaluationWorkspacePolicyError("snapshot root does not match identity")
        root = _canonical_directory(snapshot.root, "snapshot root")
        if root != snapshot.root:
            raise EvaluationWorkspacePolicyError("snapshot root is not canonical")
        try:
            manifest_bytes = self._artifact_store.read(cast(ArtifactRef, snapshot.manifest_ref))
        except (ArtifactError, OSError, ValueError) as error:
            raise EvaluationWorkspaceArtifactError(
                "evaluation manifest could not be verified"
            ) from error
        if hashlib.sha256(manifest_bytes).hexdigest() != snapshot.manifest_hash:
            raise EvaluationWorkspaceArtifactError("evaluation manifest hash mismatch")
        expected_manifest = _manifest_bytes(
            snapshot.snapshot_id,
            workspace,
            snapshot.head_commit,
            snapshot.entries,
            snapshot.evidence,
        )
        if manifest_bytes != expected_manifest:
            raise EvaluationWorkspaceArtifactError("evaluation manifest content mismatch")
        _verify_snapshot_files(root, snapshot.entries)
        expected_identity = _identity_hash(
            snapshot.snapshot_id,
            workspace,
            snapshot.head_commit,
            snapshot.evidence.diff_hash,
            snapshot.manifest_hash,
        )
        if expected_identity != snapshot.identity_hash:
            raise EvaluationWorkspaceArtifactError("evaluation identity hash mismatch")
        return snapshot.evidence

    async def _git_state(
        self,
        workspace: Workspace,
        source_identity: tuple[int, int],
        control: _GitControl,
    ) -> _GitState:
        _verify_git_control(control)
        _assert_path_matches_fd(workspace.worktree_path, source_identity)
        inside = _decode_line(
            await self._git_output(workspace, control, ("rev-parse", "--is-inside-work-tree")),
            "worktree state",
        )
        if inside != "true":
            raise EvaluationWorkspacePolicyError("Git worktree identity mismatch")
        head = _decode_line(
            await self._git_output(workspace, control, ("rev-parse", "HEAD")),
            "HEAD",
        )
        if head != workspace.base_commit:
            raise EvaluationWorkspaceChangedError("workspace HEAD differs from approved base")
        tracked = _decode_paths(
            await self._git_output(
                control=control, workspace=workspace, arguments=("ls-files", "-z", "--cached", "--")
            )
        )
        untracked = _decode_paths(
            await self._git_output(
                workspace,
                control,
                ("ls-files", "-z", "--others", "--exclude-standard", "--"),
            )
        )
        ignored = _decode_paths(
            await self._git_output(
                workspace,
                control,
                ("ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--"),
            )
        )
        changed_tracked = _decode_paths(
            await self._git_output(
                workspace,
                control,
                ("diff", "--name-only", "-z", "HEAD", "--"),
            )
        )
        if (
            set(tracked) & set(untracked)
            or set(tracked) & set(ignored)
            or set(untracked) & set(ignored)
        ):
            raise EvaluationWorkspaceCommandError("Git classifications overlap")
        _assert_path_matches_fd(workspace.worktree_path, source_identity)
        _verify_git_control(control)
        return _GitState(head, tracked, untracked, ignored, changed_tracked)

    async def _git_output(
        self,
        workspace: Workspace,
        control: _GitControl,
        arguments: tuple[str, ...],
    ) -> bytes:
        returncode, output = await self._git_result(workspace, control, arguments)
        if returncode != 0:
            raise EvaluationWorkspaceCommandError("bounded Git metadata command failed")
        return output

    async def _git_diff_check(self, workspace: Workspace, control: _GitControl) -> bool:
        returncode, _ = await self._git_result(
            workspace,
            control,
            ("diff", "--no-ext-diff", "--no-textconv", "--check", "HEAD", "--"),
        )
        if returncode not in (0, 1):
            raise EvaluationWorkspaceCommandError("bounded Git diff check failed")
        return returncode == 1

    async def _git_result(
        self,
        workspace: Workspace,
        control: _GitControl,
        arguments: tuple[str, ...],
    ) -> tuple[int, bytes]:
        attempt_id = AttemptId(f"att-{uuid.uuid4().hex[:12]}")
        request = ProcessRequest(
            argv=(
                str(self._git_executable),
                "--no-optional-locks",
                f"--git-dir={control.root}",
                "--work-tree=.",
                "-c",
                _HOOKS_CONFIG,
                *arguments,
            ),
            executable=self._git_executable,
            cwd=workspace.worktree_path,
            policy=ProcessPolicy(
                allowed_executables=(self._git_executable,),
                allowed_cwd_roots=(workspace.worktree_path,),
            ),
            trust_profile=TrustProfile.TRUSTED,
            redaction_secrets=(
                str(workspace.factory_home),
                str(workspace.repository),
                str(workspace.worktree_path),
                str(workspace.lock_path),
            ),
            run_id=workspace.run_id,
            attempt_id=attempt_id,
        )
        try:
            _verify_git_control(control)
            result = await self._process_runner.run(request)
            _verify_git_control(control)
            if result.truncated or result.stdout_ref is None:
                raise EvaluationWorkspaceCommandError("bounded Git metadata command failed")
            return result.returncode, self._artifact_store.read(
                cast(ArtifactRef, result.stdout_ref)
            )
        except EvaluationWorkspaceCommandError:
            raise
        except (ArtifactError, OSError, ProcessExecutionError, ValueError) as error:
            raise EvaluationWorkspaceCommandError("Git metadata could not be captured") from error


def _store_manifest(store: ArtifactStore, reference: ArtifactRef, payload: bytes) -> None:
    try:
        store.put(reference, payload)
    except (ArtifactError, OSError, ValueError) as error:
        raise EvaluationWorkspaceArtifactError("evaluation manifest could not be stored") from error


def _authorize_workspace(workspace: Workspace) -> Workspace:
    factory_home = _canonical_directory(workspace.factory_home, "factory home")
    repository = _canonical_directory(workspace.repository, "repository")
    if factory_home != workspace.factory_home or repository != workspace.repository:
        raise EvaluationWorkspacePolicyError("persisted workspace roots are not canonical")
    expected_worktree = (
        factory_home
        / _WORKTREES_DIR
        / _worktree_repository_slug(repository)
        / workspace.run_id.value
        / workspace.task_id.value
    )
    expected_lock = (
        factory_home
        / "locks"
        / _worktree_repository_slug(repository)
        / workspace.run_id.value
        / f"{workspace.task_id.value}.lock"
    )
    if workspace.worktree_path != expected_worktree or workspace.lock_path != expected_lock:
        raise EvaluationWorkspacePolicyError("persisted workspace identity is not authorized")
    worktree = _canonical_directory(workspace.worktree_path, "worktree")
    if worktree != expected_worktree:
        raise EvaluationWorkspacePolicyError("worktree path is not canonical")
    return workspace


def _create_snapshot_id(factory: Callable[[], str]) -> str:
    snapshot_id = factory()
    if not _SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
        raise EvaluationWorkspacePolicyError("snapshot identity is invalid")
    return snapshot_id


def _borrow_lock_lease(
    capability: WorkspaceLockCapability,
    workspace: Workspace,
) -> WorkspaceLockLease:
    try:
        return capability.borrow_lock_lease(workspace)
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise EvaluationWorkspacePolicyError("workspace lock capability is unavailable") from error


def _assert_lock_lease_active(lease: WorkspaceLockLease) -> None:
    try:
        active = lease.active
    except OSError as error:
        raise EvaluationWorkspaceChangedError("workspace lock authority changed") from error
    if not active:
        raise EvaluationWorkspaceChangedError("workspace lock authority changed")


def _verify_git_and_source_identity(
    source_fd: int,
    workspace: Workspace,
    source_identity: tuple[int, int],
) -> Path:
    git_directory = _validate_git_link(source_fd, workspace)
    _assert_path_matches_fd(workspace.worktree_path, source_identity)
    return git_directory


def _verify_final_source(
    source_fd: int,
    workspace: Workspace,
    source_identity: tuple[int, int],
    entries: tuple[ManifestEntry, ...],
    max_files: int,
) -> None:
    _assert_path_matches_fd(workspace.worktree_path, source_identity)
    _verify_source(source_fd, entries)
    git_directory = _validate_git_link(source_fd, workspace)
    _validate_workspace_head(workspace, git_directory)
    present_paths = tuple(sorted(entry.path for entry in entries if entry.present))
    if _inventory_source_paths(source_fd, max_files) != present_paths:
        raise EvaluationWorkspaceChangedError("workspace inventory changed during capture")


def _validate_workspace_head(workspace: Workspace, git_directory: Path) -> None:
    source_fd = _open_directory(git_directory)
    common_fd = _open_directory(workspace.repository / ".git")
    try:
        _validated_head_sources(source_fd, common_fd, workspace.base_commit)
    finally:
        os.close(common_fd)
        os.close(source_fd)


def _inventory_source_paths(root_fd: int, max_files: int) -> tuple[str, ...]:
    values: list[str] = []
    total_entries = 0
    total_path_bytes = 0
    stack: list[tuple[str, int]] = [("", 0)]
    while stack:
        prefix, depth = stack.pop()
        if depth > _MAX_INVENTORY_DEPTH:
            raise EvaluationWorkspacePolicyError("workspace inventory depth exceeds policy")
        directory_fd = os.dup(root_fd) if not prefix else _open_relative_directory(root_fd, prefix)
        try:
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if not prefix and entry.name == ".git":
                        continue
                    relative = f"{prefix}/{entry.name}" if prefix else entry.name
                    path_bytes = len(relative.encode("utf-8"))
                    total_entries += 1
                    total_path_bytes += path_bytes
                    if (
                        total_entries > max_files
                        or path_bytes > _MAX_GIT_LINK_BYTES
                        or total_path_bytes > _MAX_INVENTORY_PATH_BYTES
                    ):
                        raise EvaluationWorkspacePolicyError("workspace inventory exceeds policy")
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError as error:
                        raise EvaluationWorkspaceChangedError(
                            "workspace inventory changed"
                        ) from error
                    if stat.S_ISDIR(entry_stat.st_mode):
                        stack.append((relative, depth + 1))
                    else:
                        values.append(relative)
        finally:
            os.close(directory_fd)
    return tuple(sorted(values))


def _open_relative_directory(root_fd: int, relative_path: str) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in _validated_parts(relative_path):
            next_fd = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as error:
        with contextlib.suppress(OSError):
            os.close(current_fd)
        raise EvaluationWorkspaceChangedError("workspace inventory changed") from error


def _verify_stable_git_state(
    source_fd: int,
    workspace: Workspace,
    entries: tuple[ManifestEntry, ...],
    states: tuple[_GitState, _GitState],
    control: _GitControl,
) -> None:
    _verify_source(source_fd, entries)
    _validate_git_link(source_fd, workspace)
    _verify_git_control(control)
    if states[0].signature != states[1].signature:
        raise EvaluationWorkspaceChangedError("workspace changed during capture")


def _classifications(
    state: _GitState,
    max_files: int,
) -> tuple[tuple[str, FileClassification], ...]:
    values = {
        **dict.fromkeys(state.tracked, FileClassification.TRACKED),
        **dict.fromkeys(state.untracked, FileClassification.UNTRACKED),
        **dict.fromkeys(state.ignored, FileClassification.IGNORED),
    }
    if len(values) > max_files:
        raise EvaluationWorkspacePolicyError("evaluation file count exceeds policy")
    return tuple(sorted(values.items()))


def _materialize(
    source_fd: int,
    staging_root: Path,
    classifications: tuple[tuple[str, FileClassification], ...],
    max_total_bytes: int,
    changed_paths: frozenset[str],
) -> tuple[tuple[ManifestEntry, ...], tuple[SecretFinding, ...], bool]:
    entries: list[ManifestEntry] = []
    all_findings: set[SecretFinding] = set()
    evidence_bytes = 0
    total_bytes = 0
    content_diff_check_failed = False
    for relative_path, classification in classifications:
        credential_finding = _credential_path_finding(relative_path)
        try:
            content = _scan_source_file(
                source_fd,
                relative_path,
                max_total_bytes - total_bytes,
            )
        except FileNotFoundError:
            if classification is not FileClassification.TRACKED:
                raise EvaluationWorkspaceChangedError(
                    "non-tracked source disappeared during capture"
                ) from None
            entry = ManifestEntry(
                path=relative_path,
                classification=classification,
                present=False,
                included=False,
                size_bytes=0,
                sha256=_EMPTY_SHA256,
                binary=False,
            )
            entries.append(entry)
            continue
        total_bytes += content.size_bytes
        if total_bytes > max_total_bytes:
            raise EvaluationWorkspacePolicyError("evaluation bytes exceed policy")
        if relative_path in changed_paths:
            content_diff_check_failed = content_diff_check_failed or content.diff_check_failed
        findings = set(content.findings)
        if credential_finding is not None:
            findings.add(credential_finding)
        evidence_bytes = _merge_secret_findings(all_findings, findings, evidence_bytes)
        included = not findings
        if included:
            _copy_source_file(
                source_fd,
                relative_path,
                staging_root,
                content,
            )
        entries.append(
            ManifestEntry(
                path=relative_path,
                classification=classification,
                present=True,
                included=included,
                size_bytes=content.size_bytes,
                sha256=content.sha256,
                binary=content.binary,
            )
        )
    return (
        tuple(entries),
        tuple(sorted(all_findings, key=lambda item: (item.path, item.kind))),
        content_diff_check_failed,
    )


def _merge_secret_findings(
    findings: set[SecretFinding],
    candidates: set[SecretFinding],
    evidence_bytes: int,
) -> int:
    for candidate in candidates - findings:
        evidence_bytes += (
            len(candidate.kind.encode()) + len(candidate.path.encode()) + len(candidate.fingerprint)
        )
        findings.add(candidate)
        if len(findings) > _MAX_SECRET_FINDINGS or evidence_bytes > _MAX_SECRET_EVIDENCE_BYTES:
            raise EvaluationWorkspacePolicyError("secret evidence exceeds policy")
    return evidence_bytes


def _scan_source_file(root_fd: int, relative_path: str, max_bytes: int) -> _SourceContent:
    fd = _open_relative_file(root_fd, relative_path)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise EvaluationWorkspacePolicyError("repository entry is not a regular file")
        if before.st_size > max_bytes:
            raise EvaluationWorkspacePolicyError("evaluation bytes exceed policy")
        digest = hashlib.sha256()
        total = 0
        binary = False
        tail = b""
        line_tail = b""
        diff_check_failed = False
        findings: set[SecretFinding] = set()
        finding_bytes = 0
        while True:
            chunk = os.read(fd, _COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise EvaluationWorkspacePolicyError("evaluation bytes exceed policy")
            binary = binary or b"\x00" in chunk
            line_tail, violation = _scan_diff_check_lines(line_tail, chunk)
            diff_check_failed = diff_check_failed or violation
            scan_data = tail + chunk
            finding_bytes = _merge_secret_findings(
                findings,
                _content_findings(relative_path, scan_data),
                finding_bytes,
            )
            tail = scan_data[-_SECRET_SCAN_OVERLAP:]
        after = os.fstat(fd)
    finally:
        os.close(fd)
    before_identity = _stat_identity(before)
    if before_identity != _stat_identity(after) or total != after.st_size:
        raise EvaluationWorkspaceChangedError("source changed while it was scanned")
    return _SourceContent(
        size_bytes=total,
        sha256=digest.hexdigest(),
        binary=binary,
        stat_identity=before_identity,
        findings=tuple(sorted(findings, key=lambda item: (item.path, item.kind))),
        diff_check_failed=diff_check_failed or _diff_check_line_violation(line_tail),
    )


def _scan_diff_check_lines(tail: bytes, chunk: bytes) -> tuple[bytes, bool]:
    combined = tail + chunk
    lines = combined.splitlines(keepends=True)
    tail = lines.pop() if lines and not lines[-1].endswith((b"\n", b"\r")) else b""
    return tail, any(_diff_check_line_violation(line) for line in lines)


def _diff_check_line_violation(line: bytes) -> bool:
    content = line.rstrip(b"\r\n")
    return content.endswith((b" ", b"\t")) or content.startswith(
        (b"<<<<<<<", b"=======", b">>>>>>>")
    )


def _copy_source_file(
    source_root_fd: int,
    relative_path: str,
    destination_root: Path,
    expected: _SourceContent,
) -> None:
    source_fd = _open_relative_file(source_root_fd, relative_path)
    destination_directory_fd, destination_fd, temp_name, final_name = _open_destination_file(
        destination_root,
        relative_path,
    )
    try:
        source_stat = os.fstat(source_fd)
        if _stat_identity(source_stat) != expected.stat_identity:
            raise EvaluationWorkspaceChangedError("source changed before private copy")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source_fd, _COPY_CHUNK_BYTES)
            if not chunk:
                break
            _write_all(destination_fd, chunk)
            digest.update(chunk)
            total += len(chunk)
        os.fsync(destination_fd)
        if total != expected.size_bytes or digest.hexdigest() != expected.sha256:
            raise EvaluationWorkspaceChangedError("source changed while copied")
        os.fchmod(destination_fd, _LOCK_FILE_MODE)
        os.link(
            temp_name,
            final_name,
            src_dir_fd=destination_directory_fd,
            dst_dir_fd=destination_directory_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        raise EvaluationWorkspacePolicyError("private snapshot copy failed") from error
    finally:
        os.close(source_fd)
        os.close(destination_fd)
        with contextlib.suppress(OSError):
            os.unlink(temp_name, dir_fd=destination_directory_fd)
        os.close(destination_directory_fd)


def _verify_source(root_fd: int, entries: tuple[ManifestEntry, ...]) -> None:
    for entry in entries:
        try:
            content = _scan_source_file(root_fd, entry.path, entry.size_bytes)
        except FileNotFoundError:
            if entry.present:
                raise EvaluationWorkspaceChangedError("source changed after capture") from None
            continue
        except EvaluationWorkspacePolicyError as error:
            raise EvaluationWorkspaceChangedError("source changed after capture") from error
        if (
            not entry.present
            or content.size_bytes != entry.size_bytes
            or content.sha256 != entry.sha256
        ):
            raise EvaluationWorkspaceChangedError("source changed after capture")


def _verify_snapshot_files(root: Path, entries: tuple[ManifestEntry, ...]) -> None:
    expected_paths = {entry.path for entry in entries if entry.included}
    actual_paths: set[str] = set()
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in tuple(directory_names):
            child = directory_path / name
            child_stat = os.lstat(child)
            if stat.S_ISLNK(child_stat.st_mode) or not stat.S_ISDIR(child_stat.st_mode):
                raise EvaluationWorkspacePolicyError("snapshot contains unsafe directory")
        for name in file_names:
            child = directory_path / name
            relative = child.relative_to(root).as_posix()
            child_stat = os.lstat(child)
            if stat.S_ISLNK(child_stat.st_mode) or not stat.S_ISREG(child_stat.st_mode):
                raise EvaluationWorkspacePolicyError("snapshot contains unsafe file")
            actual_paths.add(relative)
    if actual_paths != expected_paths:
        raise EvaluationWorkspaceArtifactError("snapshot file set differs from manifest")
    root_fd = _open_directory(root)
    try:
        for entry in entries:
            if not entry.included:
                continue
            content = _scan_source_file(root_fd, entry.path, entry.size_bytes)
            if content.size_bytes != entry.size_bytes or content.sha256 != entry.sha256:
                raise EvaluationWorkspaceArtifactError("snapshot content hash mismatch")
    finally:
        os.close(root_fd)


def _evidence(
    state: _GitState,
    entries: tuple[ManifestEntry, ...],
    findings: tuple[SecretFinding, ...],
    diff_hash: str,
    diff_check_failed: bool,
) -> RepositoryEvidence:
    binary = tuple(sorted(entry.path for entry in entries if entry.binary))
    changed = tuple(sorted(set(state.changed_tracked) | set(state.untracked) | set(state.ignored)))
    return RepositoryEvidence(
        tracked_paths=state.tracked,
        untracked_paths=state.untracked,
        ignored_paths=state.ignored,
        changed_paths=changed,
        binary_paths=binary,
        secret_findings=findings,
        diff_hash=diff_hash,
        diff_check_failed=diff_check_failed,
    )


def _manifest_bytes(
    snapshot_id: str,
    workspace: Workspace,
    head_commit: str,
    entries: tuple[ManifestEntry, ...],
    evidence: RepositoryEvidence,
) -> bytes:
    payload = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "run_id": workspace.run_id.value,
        "task_id": workspace.task_id.value,
        "repository_id": _evaluation_repository_id(workspace.repository),
        "base_commit": workspace.base_commit,
        "head_commit": head_commit,
        "lifecycle": SnapshotLifecycle.VERIFIED.value,
        "diff_hash": evidence.diff_hash,
        "diff_check_failed": evidence.diff_check_failed,
        "entries": [
            {
                "path": entry.path,
                "classification": entry.classification.value,
                "present": entry.present,
                "included": entry.included,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
                "binary": entry.binary,
            }
            for entry in entries
        ],
        "secret_findings": [
            {
                "kind": finding.kind,
                "path": finding.path,
                "fingerprint": finding.fingerprint,
            }
            for finding in evidence.secret_findings
        ],
    }
    return (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("ascii")


def _entries_hash(entries: tuple[ManifestEntry, ...]) -> str:
    payload = "\n".join(
        f"{entry.path}\0{entry.classification.value}\0{int(entry.present)}\0"
        f"{int(entry.included)}\0{entry.size_bytes}\0{entry.sha256}\0{int(entry.binary)}"
        for entry in entries
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _diff_hash(state: _GitState, entries_hash: str) -> str:
    payload = f"{state.signature}\0{entries_hash}".encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _identity_hash(
    snapshot_id: str,
    workspace: Workspace,
    head_commit: str,
    diff_hash: str,
    manifest_hash: str,
) -> str:
    payload = "\0".join(
        (
            snapshot_id,
            workspace.run_id.value,
            workspace.task_id.value,
            _evaluation_repository_id(workspace.repository),
            workspace.base_commit,
            head_commit,
            diff_hash,
            manifest_hash,
        )
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _credential_path_finding(relative_path: str) -> SecretFinding | None:
    name = PurePosixPath(relative_path).name.lower()
    if (
        name not in _CREDENTIAL_NAMES
        and not name.startswith(".env.")
        and not name.endswith(_CREDENTIAL_SUFFIXES)
    ):
        return None
    return SecretFinding(
        kind="credential-path",
        path=relative_path,
        fingerprint=_fingerprint("credential-path", relative_path, relative_path.encode()),
    )


def _content_findings(relative_path: str, data: bytes) -> set[SecretFinding]:
    findings: set[SecretFinding] = set()
    for detected in detect_secrets(data):
        findings.add(
            SecretFinding(
                kind=detected.kind,
                path=relative_path,
                fingerprint=_fingerprint(detected.kind, relative_path, detected.value),
            )
        )
    return findings


def _fingerprint(kind: str, relative_path: str, secret: bytes) -> str:
    return hashlib.sha256(
        kind.encode("ascii") + b"\0" + relative_path.encode("utf-8") + b"\0" + secret
    ).hexdigest()


def _prepare_staging(workspace: Workspace, snapshot_id: str) -> tuple[Path, Path]:
    final_root = _snapshot_root(workspace, snapshot_id)
    final_directory = final_root.parent
    parent = final_directory.parent
    _ensure_owned_directories(parent, workspace.factory_home)
    staging = parent / f".{snapshot_id}.{uuid.uuid4().hex}.tmp"
    workspace_root = staging / "workspace"
    staging_created = False
    try:
        os.mkdir(staging, _DIRECTORY_MODE)
        staging_created = True
        os.mkdir(workspace_root, _DIRECTORY_MODE)
    except OSError as error:
        if staging_created:
            _remove_owned_staging(workspace_root)
        raise EvaluationWorkspacePolicyError("snapshot staging could not be created") from error
    if os.path.lexists(final_directory):
        _remove_owned_staging(workspace_root)
        raise EvaluationWorkspacePolicyError("snapshot identity already exists")
    return workspace_root, final_root


def _snapshot_root(workspace: Workspace, snapshot_id: str) -> Path:
    return (
        workspace.factory_home
        / _EVALUATIONS_DIR
        / _evaluation_repository_id(workspace.repository)
        / workspace.run_id.value
        / workspace.task_id.value
        / snapshot_id
        / "workspace"
    )


def _publish_staging(staging_root: Path, final_directory: Path) -> None:
    staging_directory = staging_root.parent
    try:
        os.rename(staging_directory, final_directory)
    except OSError as error:
        raise EvaluationWorkspacePolicyError(
            "snapshot could not be published atomically"
        ) from error


def _make_read_only(snapshot_directory: Path) -> None:
    for directory, directory_names, file_names in os.walk(snapshot_directory, topdown=False):
        directory_path = Path(directory)
        for name in file_names:
            os.chmod(directory_path / name, _READ_ONLY_FILE_MODE)
        for name in directory_names:
            os.chmod(directory_path / name, _READ_ONLY_DIRECTORY_MODE)
        os.chmod(directory_path, _READ_ONLY_DIRECTORY_MODE)


def _remove_owned_staging(staging_root: Path) -> None:
    staging_directory = staging_root.parent
    if not staging_directory.name.startswith(".snap-"):
        return
    with contextlib.suppress(OSError):
        shutil.rmtree(staging_directory)


def _remove_owned_snapshot(
    snapshot_directory: Path,
    workspace: Workspace,
    snapshot_id: str,
) -> None:
    if snapshot_directory != _snapshot_root(workspace, snapshot_id).parent:
        return
    parent_fd: int | None = None
    quarantine_fd: int | None = None
    quarantine_name = f".{snapshot_id}.{uuid.uuid4().hex}.discard"
    try:
        parent_fd = _open_directory(snapshot_directory.parent)
        os.rename(
            snapshot_directory.name,
            quarantine_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        quarantine_fd = os.open(quarantine_name, flags, dir_fd=parent_fd)
        _remove_tree_contents(quarantine_fd)
        os.close(quarantine_fd)
        quarantine_fd = None
        os.rmdir(quarantine_name, dir_fd=parent_fd)
    except OSError:
        return
    finally:
        if quarantine_fd is not None:
            os.close(quarantine_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _remove_tree_contents(directory_fd: int) -> None:
    os.fchmod(directory_fd, _DIRECTORY_MODE)
    for entry in tuple(os.scandir(directory_fd)):
        if entry.is_dir(follow_symlinks=False):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
            try:
                _remove_tree_contents(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(entry.name, dir_fd=directory_fd)
        else:
            os.unlink(entry.name, dir_fd=directory_fd)


def _open_destination_file(root: Path, relative_path: str) -> tuple[int, int, str, str]:
    parts = _validated_parts(relative_path)
    current_fd = _open_directory(root)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, _DIRECTORY_MODE, dir_fd=current_fd)
            next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        final_name = parts[-1]
        temp_name = f".{final_name}.{uuid.uuid4().hex}.copying"
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        destination_fd = os.open(
            temp_name,
            file_flags,
            _LOCK_FILE_MODE,
            dir_fd=current_fd,
        )
        return current_fd, destination_fd, temp_name, final_name
    except OSError as error:
        os.close(current_fd)
        raise EvaluationWorkspacePolicyError("snapshot destination is unsafe") from error


def _open_relative_file(root_fd: int, relative_path: str) -> int:
    parts = _validated_parts(relative_path)
    current_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current_fd,
        )
    except OSError as error:
        if isinstance(error, FileNotFoundError):
            raise
        raise EvaluationWorkspacePolicyError("repository path cannot be opened safely") from error
    finally:
        os.close(current_fd)


def _open_directory(path: Path) -> int:
    if not path.is_absolute():
        raise EvaluationWorkspacePolicyError("directory path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd: int | None = None
    try:
        current_fd = os.open(path.anchor, flags)
        for part in path.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as error:
        if current_fd is not None:
            with contextlib.suppress(OSError):
                os.close(current_fd)
        raise EvaluationWorkspacePolicyError("directory cannot be opened safely") from error


def _directory_identity(value: os.stat_result) -> tuple[int, int]:
    return (value.st_dev, value.st_ino)


def _assert_path_matches_fd(path: Path, expected: tuple[int, int]) -> None:
    actual_fd = _open_directory(path)
    try:
        actual = _directory_identity(os.fstat(actual_fd))
    finally:
        os.close(actual_fd)
    if actual != expected:
        raise EvaluationWorkspaceChangedError("workspace directory identity changed")


def _validated_parts(relative_path: str) -> tuple[str, ...]:
    if not relative_path or "\\" in relative_path or "\x00" in relative_path:
        raise EvaluationWorkspacePolicyError("Git returned an unsafe repository path")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise EvaluationWorkspacePolicyError("Git returned an unsafe repository path")
    if pure.parts[0] == ".git":
        raise EvaluationWorkspacePolicyError("Git metadata cannot enter the snapshot")
    return pure.parts


def _decode_paths(data: bytes) -> tuple[str, ...]:
    if not data:
        return ()
    values: set[str] = set()
    for raw_path in data.split(b"\0"):
        if not raw_path:
            continue
        try:
            path = raw_path.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise EvaluationWorkspaceCommandError("Git path encoding is invalid") from error
        _validated_parts(path)
        values.add(path)
    return tuple(sorted(values))


def _decode_line(data: bytes, label: str) -> str:
    try:
        value = data.decode("utf-8", errors="strict").strip()
    except UnicodeError as error:
        raise EvaluationWorkspaceCommandError("Git identity encoding is invalid") from error
    if not value or "\n" in value:
        raise EvaluationWorkspaceCommandError(f"Git returned invalid {label}")
    return value


def _canonical_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise EvaluationWorkspacePolicyError(f"{label} must be absolute")
    _assert_no_symlink_components(path)
    try:
        resolved = path.resolve(strict=True)
        path_stat = os.lstat(resolved)
    except OSError as error:
        raise EvaluationWorkspacePolicyError(f"{label} cannot be resolved") from error
    if not stat.S_ISDIR(path_stat.st_mode) or path_stat.st_uid != os.getuid():
        raise EvaluationWorkspacePolicyError(f"{label} identity is invalid")
    return resolved


def _assert_no_symlink_components(path: Path) -> None:
    if not path.is_absolute():
        raise EvaluationWorkspacePolicyError("path must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            current_stat = os.lstat(current)
        except OSError as error:
            raise EvaluationWorkspacePolicyError("path component cannot be inspected") from error
        if stat.S_ISLNK(current_stat.st_mode):
            raise EvaluationWorkspacePolicyError("path contains a symlink")


def _ensure_owned_directories(path: Path, factory_home: Path) -> None:
    try:
        relative = path.relative_to(factory_home)
    except ValueError as error:
        raise EvaluationWorkspacePolicyError("snapshot path escapes factory home") from error
    current = factory_home
    for part in relative.parts:
        current /= part
        with contextlib.suppress(FileExistsError):
            os.mkdir(current, _DIRECTORY_MODE)
        try:
            current_stat = os.lstat(current)
        except OSError as error:
            raise EvaluationWorkspacePolicyError("snapshot parent cannot be inspected") from error
        if (
            stat.S_ISLNK(current_stat.st_mode)
            or not stat.S_ISDIR(current_stat.st_mode)
            or current_stat.st_uid != os.getuid()
        ):
            raise EvaluationWorkspacePolicyError("snapshot parent identity is invalid")
        os.chmod(current, _DIRECTORY_MODE)


def _worktree_repository_slug(repository: Path) -> str:
    name = repository.name
    if name and all(character.isalnum() or character in "._-" for character in name):
        return name
    return hashlib.sha256(str(repository).encode("utf-8")).hexdigest()[:16]


def _evaluation_repository_id(repository: Path) -> str:
    readable = _worktree_repository_slug(repository)[:32]
    digest = hashlib.sha256(str(repository).encode("utf-8")).hexdigest()[:16]
    return f"{readable}-{digest}"


def _validate_git_link(source_fd: int, workspace: Workspace) -> Path:
    try:
        link_fd = os.open(
            ".git",
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=source_fd,
        )
    except OSError as error:
        raise EvaluationWorkspacePolicyError("worktree Git identity is unavailable") from error
    try:
        link_stat = os.fstat(link_fd)
        data = os.read(link_fd, _MAX_GIT_LINK_BYTES + 1)
    finally:
        os.close(link_fd)
    if not stat.S_ISREG(link_stat.st_mode) or len(data) > _MAX_GIT_LINK_BYTES:
        raise EvaluationWorkspacePolicyError("worktree Git identity is invalid")
    prefix = b"gitdir: "
    if not data.startswith(prefix) or not data.endswith(b"\n") or b"\n" in data[:-1]:
        raise EvaluationWorkspacePolicyError("worktree Git identity is invalid")
    try:
        git_directory = Path(data[len(prefix) : -1].decode("utf-8", errors="strict"))
    except UnicodeError as error:
        raise EvaluationWorkspacePolicyError("worktree Git identity encoding is invalid") from error
    expected_common = workspace.repository / ".git"
    if (
        not git_directory.is_absolute()
        or git_directory.parent.name != "worktrees"
        or git_directory.parent.parent != expected_common
    ):
        raise EvaluationWorkspacePolicyError("worktree belongs to another repository")
    common = _canonical_directory(git_directory.parent.parent, "Git common directory")
    if common != expected_common:
        raise EvaluationWorkspacePolicyError("worktree repository identity mismatch")
    _assert_no_symlink_components(git_directory)
    canonical_git_directory = _canonical_directory(git_directory, "Git worktree directory")
    if canonical_git_directory != git_directory:
        raise EvaluationWorkspacePolicyError("worktree Git directory is not canonical")
    backpointer = git_directory / "gitdir"
    _assert_no_symlink_components(backpointer)
    try:
        backpointer_fd = os.open(
            backpointer,
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            backpointer_stat = os.fstat(backpointer_fd)
            backpointer_data = os.read(backpointer_fd, _MAX_GIT_LINK_BYTES + 1)
        finally:
            os.close(backpointer_fd)
    except OSError as error:
        raise EvaluationWorkspacePolicyError("worktree Git backpointer is unavailable") from error
    expected_backpointer = f"{workspace.worktree_path / '.git'}\n".encode()
    if (
        not stat.S_ISREG(backpointer_stat.st_mode)
        or len(backpointer_data) > _MAX_GIT_LINK_BYTES
        or backpointer_data != expected_backpointer
    ):
        raise EvaluationWorkspacePolicyError("worktree Git backpointer mismatch")
    return git_directory


@contextlib.contextmanager
def _private_git_control(
    workspace: Workspace,
    git_directory: Path,
) -> Generator[_GitControl]:
    source_fd = _open_directory(git_directory)
    source_identity = _directory_identity(os.fstat(source_fd))
    common_fd = _open_directory(workspace.repository / ".git")
    common_identity = _directory_identity(os.fstat(common_fd))
    root = Path(tempfile.mkdtemp(prefix=".aif-git-", dir=workspace.factory_home))
    os.chmod(root, _DIRECTORY_MODE)
    root_fd = -1
    try:
        head_source, common_values = _validated_head_sources(
            source_fd,
            common_fd,
            workspace.base_commit,
        )
        source_values = (
            ("HEAD", head_source),
            ("index", _read_git_control_file(source_fd, "index", _MAX_GIT_INDEX_BYTES)),
        )
        os.mkdir(root / "objects", _DIRECTORY_MODE)
        os.mkdir(root / "objects" / "info", _DIRECTORY_MODE)
        os.mkdir(root / "info", _DIRECTORY_MODE)
        os.mkdir(root / "refs", _DIRECTORY_MODE)
        exclude = _try_read_git_control_file(common_fd, "info/exclude", _MAX_GIT_INDEX_BYTES)
        exclude_data = exclude if exclude is not None else b""
        if exclude is not None:
            common_values = (*common_values, ("info/exclude", exclude))
        private_values = (
            ("HEAD", f"{workspace.base_commit}\n".encode("ascii")),
            ("index", source_values[1][1]),
            ("info/exclude", exclude_data),
            (
                "objects/info/alternates",
                f"{workspace.repository / '.git' / 'objects'}\n".encode(),
            ),
        )
        for name, data in private_values:
            _write_private_control_file(root, name, data)
        _make_git_control_read_only(root)
        root_fd = _open_directory(root)
        control = _GitControl(
            root=root,
            root_fd=root_fd,
            root_identity=_directory_identity(os.fstat(root_fd)),
            source_fd=source_fd,
            source_identity=source_identity,
            source_hashes=_hash_named_values(source_values),
            common_fd=common_fd,
            common_identity=common_identity,
            common_hashes=_hash_named_values(common_values),
            common_absent=() if exclude is not None else ("info/exclude",),
            private_hashes=_hash_named_values(private_values),
        )
        _verify_git_control(control)
        yield control
        _verify_git_control(control)
    finally:
        if root_fd >= 0:
            os.close(root_fd)
        os.close(common_fd)
        os.close(source_fd)
        _make_git_control_writable(root)
        shutil.rmtree(root, ignore_errors=False)


def _hash_named_values(values: tuple[tuple[str, bytes], ...]) -> tuple[tuple[str, str], ...]:
    return tuple((name, hashlib.sha256(data).hexdigest()) for name, data in values)


def _make_git_control_read_only(root: Path) -> None:
    for directory, directory_names, file_names in os.walk(root, topdown=False):
        directory_path = Path(directory)
        for name in file_names:
            os.chmod(directory_path / name, _READ_ONLY_FILE_MODE)
        for name in directory_names:
            os.chmod(directory_path / name, _READ_ONLY_DIRECTORY_MODE)
        os.chmod(directory_path, _READ_ONLY_DIRECTORY_MODE)


def _make_git_control_writable(root: Path) -> None:
    for directory, directory_names, file_names in os.walk(root, topdown=True):
        directory_path = Path(directory)
        os.chmod(directory_path, _DIRECTORY_MODE)
        for name in directory_names:
            os.chmod(directory_path / name, _DIRECTORY_MODE)
        for name in file_names:
            os.chmod(directory_path / name, _LOCK_FILE_MODE)


def _read_git_control_file(directory_fd: int, name: str, limit: int) -> bytes:
    try:
        fd = _open_relative_file(directory_fd, name)
        try:
            file_stat = os.fstat(fd)
            data = os.read(fd, limit + 1)
        finally:
            os.close(fd)
    except OSError as error:
        raise EvaluationWorkspacePolicyError("Git control file is unavailable") from error
    if not stat.S_ISREG(file_stat.st_mode) or len(data) > limit:
        raise EvaluationWorkspacePolicyError("Git control file violates policy")
    return data


def _validated_head_sources(
    source_fd: int,
    common_fd: int,
    baseline: str,
) -> tuple[bytes, tuple[tuple[str, bytes], ...]]:
    head = _read_git_control_file(source_fd, "HEAD", _MAX_GIT_LINK_BYTES)
    prefix = b"ref: "
    if not head.startswith(prefix):
        if head.strip().decode("ascii", errors="strict") != baseline:
            raise EvaluationWorkspaceChangedError("workspace HEAD differs from approved base")
        return head, ()
    try:
        reference = head[len(prefix) :].strip().decode("ascii", errors="strict")
    except UnicodeError as error:
        raise EvaluationWorkspacePolicyError("workspace HEAD encoding is invalid") from error
    _validated_parts(reference)
    loose = _try_read_git_control_file(common_fd, reference, _MAX_GIT_LINK_BYTES)
    if loose is not None:
        if loose.strip().decode("ascii", errors="strict") != baseline:
            raise EvaluationWorkspaceChangedError("workspace HEAD ref differs from approved base")
        return head, ((reference, loose),)
    packed = _read_git_control_file(common_fd, "packed-refs", _MAX_GIT_INDEX_BYTES)
    resolved = _resolve_packed_ref(packed, reference)
    if resolved != baseline:
        raise EvaluationWorkspaceChangedError("workspace packed HEAD differs from approved base")
    return head, (("packed-refs", packed),)


def _try_read_git_control_file(directory_fd: int, name: str, limit: int) -> bytes | None:
    try:
        fd = _open_relative_file(directory_fd, name)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise EvaluationWorkspacePolicyError("Git HEAD ref is unavailable") from error
    try:
        file_stat = os.fstat(fd)
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if not stat.S_ISREG(file_stat.st_mode) or len(data) > limit:
        raise EvaluationWorkspacePolicyError("Git HEAD ref violates policy")
    return data


def _resolve_packed_ref(data: bytes, reference: str) -> str:
    suffix = f" {reference}".encode("ascii")
    matches = [line[:40] for line in data.splitlines() if line.endswith(suffix)]
    if len(matches) != 1:
        raise EvaluationWorkspacePolicyError("workspace packed HEAD is ambiguous")
    return matches[0].decode("ascii", errors="strict")


def _write_private_control_file(root: Path, name: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root / name, flags, _LOCK_FILE_MODE)
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as error:
        raise EvaluationWorkspacePolicyError("private Git control could not be written") from error


def _verify_git_control(control: _GitControl) -> None:
    if _directory_identity(os.fstat(control.root_fd)) != control.root_identity:
        raise EvaluationWorkspaceChangedError("private Git control identity changed")
    _assert_path_matches_fd(control.root, control.root_identity)
    expected_private_paths = tuple(sorted(name for name, _ in control.private_hashes))
    if (
        _inventory_source_paths(control.root_fd, len(expected_private_paths) * 4)
        != expected_private_paths
    ):
        raise EvaluationWorkspaceChangedError("private Git control inventory changed")
    if _directory_identity(os.fstat(control.source_fd)) != control.source_identity:
        raise EvaluationWorkspaceChangedError("Git control identity changed")
    _verify_named_hashes(control.source_fd, control.source_hashes, "Git control changed")
    if _directory_identity(os.fstat(control.common_fd)) != control.common_identity:
        raise EvaluationWorkspaceChangedError("Git common identity changed")
    _verify_named_hashes(control.common_fd, control.common_hashes, "Git HEAD changed")
    for name in control.common_absent:
        if _try_read_git_control_file(control.common_fd, name, _MAX_GIT_INDEX_BYTES) is not None:
            raise EvaluationWorkspaceChangedError("Git exclude policy changed")
    _verify_named_hashes(control.root_fd, control.private_hashes, "private Git control changed")


def _verify_named_hashes(
    directory_fd: int,
    hashes: tuple[tuple[str, str], ...],
    message: str,
) -> None:
    for name, expected_hash in hashes:
        data = _read_git_control_file(directory_fd, name, _MAX_GIT_INDEX_BYTES)
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_hash):
            raise EvaluationWorkspaceChangedError(message)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise EvaluationWorkspacePolicyError("private snapshot write made no progress")
        offset += written
