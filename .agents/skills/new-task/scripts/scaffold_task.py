#!/usr/bin/env python3
"""Create the next planned task contract from the normative template."""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TASK_ID = re.compile(r"TASK-(?P<number>[0-9]{3})$")
TASK_FILE = re.compile(r"task(?P<number>[1-9][0-9]*)\.md$")
RELEASE = re.compile(r"V[0-9]+\.[0-9]+$")
VALIDATION_TIMEOUT_SECONDS = 30
RISK_LEVELS = ("low", "medium", "high", "critical")
CONTROL_CHARACTER_LIMIT = 32
MAX_TITLE_LENGTH = 100


class ScaffoldError(ValueError):
    """Raised when a requested task contract is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class TaskDraft:
    task_id: str
    title: str
    release: str
    risk_level: str
    dependencies: tuple[str, ...]


def _repository_root() -> Path:
    root = Path(__file__).resolve().parents[4]
    if not (root / "AGENTS.md").is_file():
        raise ScaffoldError("repository root could not be verified")
    return root


def _next_task_number(planning: Path) -> int:
    numbers = [
        int(match["number"])
        for path in planning.glob("task*.md")
        if (match := TASK_FILE.fullmatch(path.name)) is not None
    ]
    return max(numbers, default=0) + 1


def _validate_identity(task_id: str, planning: Path) -> int:
    match = TASK_ID.fullmatch(task_id)
    if match is None:
        raise ScaffoldError("task id must match TASK-NNN")
    number = int(match["number"])
    if number != _next_task_number(planning):
        raise ScaffoldError("task id must be the next sequential id")
    return number


def _validate_dependencies(task_id: str, dependencies: tuple[str, ...], planning: Path) -> None:
    if task_id in dependencies:
        raise ScaffoldError("task cannot depend on itself")
    for dependency in dependencies:
        match = TASK_ID.fullmatch(dependency)
        if match is None or not (planning / f"task{int(match['number'])}.md").is_file():
            raise ScaffoldError("every dependency must identify an existing task")


def render_contract(template: str, draft: TaskDraft) -> str:
    """Render identity fields while preserving the normative template body."""
    dependency_field = ", ".join(draft.dependencies)
    replacements = {
        'title: "TASK-NNN — Resultado observável"': f'title: "{draft.task_id} — {draft.title}"',
        "task_id: TASK-NNN": f"task_id: {draft.task_id}",
        'release: "Vx.y"': f'release: "{draft.release}"',
        "depends_on: [TASK-NNN]": f"depends_on: [{dependency_field}]",
        "risk_level: low | medium | high | critical": f"risk_level: {draft.risk_level}",
        "# TASK-NNN — Resultado observável": f"# {draft.task_id} — {draft.title}",
    }
    rendered = template
    for source, target in replacements.items():
        if source not in rendered:
            raise ScaffoldError("task template does not match the supported contract")
        rendered = rendered.replace(source, target, 1)
    return rendered.replace("TASK-NNN", draft.task_id)


def _open_trusted_directory(root: Path, planning: Path) -> int:
    root = root.resolve(strict=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, flags)
        descriptors.append(current)
        for component in planning.relative_to(root).parts:
            current = os.open(component, flags, dir_fd=current)
            descriptors.append(current)
        descriptors.pop()
        return current
    except OSError as error:
        raise ScaffoldError("planning path must be a real repository directory") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _write_exclusive(directory_fd: int, filename: str, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(filename, flags, mode=0o600, dir_fd=directory_fd)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ScaffoldError("target task already exists") from error


def _validate_repository(root: Path, directory_fd: int, target: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository validator
        [sys.executable, str(root / "scripts" / "validate_tasks.py")],
        cwd=root,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=VALIDATION_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode == 0:
        return
    with contextlib.suppress(FileNotFoundError):
        os.unlink(target.name, dir_fd=directory_fd)
    raise ScaffoldError("generated contract failed repository validation")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--risk-level", choices=RISK_LEVELS, required=True)
    parser.add_argument("--depends-on", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        root = _repository_root()
        planning = root / "docs" / "planejamento"
        number = _validate_identity(args.task_id, planning)
        title = args.title.strip()
        if (
            not title
            or len(title) > MAX_TITLE_LENGTH
            or any(ord(character) < CONTROL_CHARACTER_LIMIT for character in title)
            or '"' in title
            or not RELEASE.fullmatch(args.release)
        ):
            raise ScaffoldError("title and release must be concrete")
        dependencies = tuple(args.depends_on)
        if len(dependencies) != len(set(dependencies)):
            raise ScaffoldError("dependencies must be unique")
        _validate_dependencies(args.task_id, dependencies, planning)
        draft = TaskDraft(
            task_id=args.task_id,
            title=title,
            release=args.release,
            risk_level=args.risk_level,
            dependencies=dependencies,
        )
        content = render_contract(
            (planning / "task-template.md").read_text(encoding="utf-8"),
            draft,
        )
        if args.dry_run:
            sys.stdout.write(content)
            return 0
        target = planning / f"task{number}.md"
        directory_fd = _open_trusted_directory(root, planning)
        try:
            _write_exclusive(directory_fd, target.name, content)
            _validate_repository(root, directory_fd, target)
        finally:
            os.close(directory_fd)
        print(f"created {target.relative_to(root)} as planned with TO_BE_PINNED")
        return 0
    except (OSError, ScaffoldError, subprocess.SubprocessError) as error:
        print(f"new-task: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
