"""Pure SPEC parser — converts Markdown text into immutable domain models.

This module never touches the filesystem, network or subprocesses.
It is a pure function from text to ``SoftwareSpec``.
"""

from __future__ import annotations

import re
from typing import Final

from ai_software_factory.core.spec_models import (
    AcceptanceCriterion,
    SoftwareSpec,
    TaskId,
    TaskSpec,
    ValidationCommand,
)

MAX_SPEC_BYTES: Final[int] = 1_048_576
MAX_TASKS: Final[int] = 200
SCHEMA_VERSION: Final[int] = 1

_FRONTMATTER_DELIMITER: Final[str] = "---"
_DASH_CHARS: Final[str] = "\u2014\\-\u2013"
_TASK_HEADING: Final[re.Pattern[str]] = re.compile(
    rf"^##\s+(TASK-\d{{3,}})\s*[{_DASH_CHARS}]\s*(.+)$"
)
_SECTION_LABEL: Final[re.Pattern[str]] = re.compile(
    r"^\*\*(Depends on|Allowed paths|Acceptance criteria|Validation commands):\*\*\s*$"
)
_AC_LINE: Final[re.Pattern[str]] = re.compile(rf"^-\s+(AC-\d{{3,}})\s*[{_DASH_CHARS}]\s*(.+)$")
_LIST_ITEM: Final[re.Pattern[str]] = re.compile(r"^-\s+(.+)$")
_DEPENDS_ITEM: Final[re.Pattern[str]] = re.compile(r"^-\s+(TASK-\d{3,})\s*$")
_INLINE_DEPENDS: Final[re.Pattern[str]] = re.compile(r"^(TASK-\d{3,})$")
_MIN_QUOTE_LEN: Final[int] = 2


class SpecParseError(ValueError):
    """Raised when the SPEC text cannot be parsed into a valid model."""


class SpecParser:
    """Stateless, pure parser — no I/O, no global state."""

    def parse(self, text: str) -> SoftwareSpec:
        if len(text.encode("utf-8")) > MAX_SPEC_BYTES:
            raise SpecParseError(f"SPEC exceeds max_spec_bytes ({MAX_SPEC_BYTES})")
        frontmatter, body = _split_frontmatter(text)
        meta = _parse_frontmatter(frontmatter)
        tasks = _parse_tasks(body)
        return SoftwareSpec(
            spec_id=meta.spec_id,
            schema_version=meta.schema_version,
            title=meta.title,
            tasks=tuple(tasks),
        )


class _FrontmatterResult:
    __slots__ = ("schema_version", "spec_id", "title")

    def __init__(self, spec_id: str, schema_version: int, title: str) -> None:
        self.spec_id = spec_id
        self.schema_version = schema_version
        self.title = title


def _split_frontmatter(text: str) -> tuple[str, str]:
    stripped = text.lstrip("\n")
    if not stripped.startswith(_FRONTMATTER_DELIMITER + "\n"):
        raise SpecParseError("missing frontmatter opening delimiter '---'")
    rest = stripped[len(_FRONTMATTER_DELIMITER) + 1 :]
    end = _find_closing_delimiter(rest)
    frontmatter = rest[:end]
    body = rest[end + len(_FRONTMATTER_DELIMITER) + 2 :]
    return frontmatter, body


def _find_closing_delimiter(rest: str) -> int:
    end = rest.find("\n" + _FRONTMATTER_DELIMITER + "\n")
    if end != -1:
        return end
    end = rest.find("\n" + _FRONTMATTER_DELIMITER)
    if end == -1:
        raise SpecParseError("missing frontmatter closing delimiter '---'")
    if rest[end + len(_FRONTMATTER_DELIMITER) + 1 :].strip():
        raise SpecParseError("missing frontmatter closing delimiter '---'")
    return end


def _parse_frontmatter(raw: str) -> _FrontmatterResult:
    fields: dict[str, str] = {}
    for lineno, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        key, value = _parse_frontmatter_line(stripped, lineno)
        if key in fields:
            raise SpecParseError(f"frontmatter line {lineno}: duplicate key '{key}'")
        fields[key] = value
    return _build_frontmatter_result(fields)


def _parse_frontmatter_line(stripped: str, lineno: int) -> tuple[str, str]:
    colon = stripped.find(":")
    if colon < 1:
        raise SpecParseError(f"frontmatter line {lineno}: invalid format")
    key = stripped[:colon].strip()
    value = stripped[colon + 1 :].strip()
    if value and value[0] in ("[", "{"):
        raise SpecParseError(f"frontmatter line {lineno}: YAML flow syntax is not allowed")
    return key, value


def _build_frontmatter_result(fields: dict[str, str]) -> _FrontmatterResult:
    for required in ("spec_id", "schema_version", "title"):
        if required not in fields:
            raise SpecParseError(f"frontmatter missing required key '{required}'")
    known = {"spec_id", "schema_version", "title"}
    unknown = sorted(set(fields) - known)
    if unknown:
        raise SpecParseError(f"frontmatter: unknown key(s): {', '.join(unknown)}")
    try:
        schema_version = int(fields["schema_version"])
    except ValueError:
        raise SpecParseError("schema_version must be integer") from None
    return _FrontmatterResult(
        spec_id=_unquote(fields["spec_id"]),
        schema_version=schema_version,
        title=_unquote(fields["title"]),
    )


def _unquote(value: str) -> str:
    if len(value) >= _MIN_QUOTE_LEN and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _parse_tasks(body: str) -> list[TaskSpec]:
    builder = _TaskBuilder()
    for line in body.splitlines():
        builder.process_line(line)
    builder.flush()
    return builder.tasks


class _TaskBuilder:
    def __init__(self) -> None:
        self.tasks: list[TaskSpec] = []
        self._current_id: str | None = None
        self._current_title: str = ""
        self._current_section: str | None = None
        self._depends: list[str] = []
        self._paths: list[str] = []
        self._acs: list[AcceptanceCriterion] = []
        self._commands: list[ValidationCommand] = []

    def process_line(self, line: str) -> None:
        heading_match = _TASK_HEADING.match(line)
        if heading_match:
            self.flush()
            self._current_id = heading_match.group(1)
            self._current_title = heading_match.group(2).strip()
            self._current_section = None
            return

        if self._current_id is None:
            return

        section_match = _SECTION_LABEL.match(line)
        if section_match:
            self._current_section = section_match.group(1)
            return

        if self._current_section is None:
            return

        self._dispatch_section(line)

    def _dispatch_section(self, line: str) -> None:
        if self._current_section == "Depends on":
            self._handle_depends(line)
        elif self._current_section == "Allowed paths":
            self._handle_path(line)
        elif self._current_section == "Acceptance criteria":
            self._handle_ac(line)
        elif self._current_section == "Validation commands":
            self._handle_command(line)

    def _handle_depends(self, line: str) -> None:
        dep_match = _DEPENDS_ITEM.match(line)
        if dep_match:
            self._depends.append(dep_match.group(1))
            return
        stripped = line.strip()
        if stripped:
            inline = _INLINE_DEPENDS.match(stripped)
            if inline:
                self._depends.append(inline.group(1))

    def _handle_path(self, line: str) -> None:
        path_match = _LIST_ITEM.match(line)
        if path_match:
            self._paths.append(path_match.group(1).strip())

    def _handle_ac(self, line: str) -> None:
        ac_match = _AC_LINE.match(line)
        if ac_match:
            self._acs.append(
                AcceptanceCriterion(
                    ac_id=ac_match.group(1),
                    description=ac_match.group(2).strip(),
                )
            )

    def _handle_command(self, line: str) -> None:
        cmd_match = _LIST_ITEM.match(line)
        if cmd_match:
            raw_cmd = cmd_match.group(1).strip()
            self._commands.append(ValidationCommand(args=tuple(raw_cmd.split())))

    def flush(self) -> None:
        if self._current_id is not None:
            self.tasks.append(
                TaskSpec(
                    task_id=TaskId(self._current_id),
                    title=self._current_title,
                    depends_on=tuple(TaskId(d) for d in self._depends),
                    allowed_paths=tuple(self._paths),
                    acceptance_criteria=tuple(self._acs),
                    validation_commands=tuple(self._commands),
                )
            )
        self._current_id = None
        self._current_title = ""
        self._current_section = None
        self._depends = []
        self._paths = []
        self._acs = []
        self._commands = []
