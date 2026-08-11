"""Unit tests for SPEC parser and validator — golden, canonical and no-effects."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Final
from unittest.mock import patch

import pytest

from ai_software_factory.application.spec_parser import SpecParseError, SpecParser
from ai_software_factory.application.spec_validator import SpecValidator
from ai_software_factory.core.spec_models import (
    AcceptanceCriterion,
    SoftwareSpec,
    TaskId,
    TaskSpec,
    ValidationCommand,
    canonical_json,
)

_EXPECTED_TASK_COUNT: Final[int] = 2
_EXPECTED_AC_COUNT: Final[int] = 2

VALID_SPEC_TEXT = """\
---
spec_id: SPEC-TEST-001
schema_version: 1
title: Test specification
---

# Test specification

## TASK-001 — First task

**Depends on:**

**Allowed paths:**
- src/foo.py
- tests/test_foo.py

**Acceptance criteria:**
- AC-001 — First criterion
- AC-002 — Second criterion

**Validation commands:**
- uv run pytest tests/test_foo.py -q

## TASK-002 — Second task

**Depends on:**
- TASK-001

**Allowed paths:**
- src/bar.py

**Acceptance criteria:**
- AC-001 — Bar works correctly

**Validation commands:**
- uv run pytest tests/test_bar.py -q
"""


def test_valid_spec_is_canonical() -> None:
    """AC-001: valid SPEC produces identical canonical JSON across runs."""
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)

    first = canonical_json(spec)
    second = canonical_json(spec)

    assert first == second
    parsed_first = json.loads(first)
    parsed_second = json.loads(second)
    assert parsed_first == parsed_second
    assert parsed_first["spec_id"] == "SPEC-TEST-001"
    assert parsed_first["schema_version"] == 1
    assert len(parsed_first["tasks"]) == _EXPECTED_TASK_COUNT


def test_parser_extracts_frontmatter_fields() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)

    assert spec.spec_id == "SPEC-TEST-001"
    assert spec.schema_version == 1
    assert spec.title == "Test specification"


def test_parser_extracts_tasks_with_dependencies() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)

    assert len(spec.tasks) == _EXPECTED_TASK_COUNT
    assert spec.tasks[0].task_id == TaskId("TASK-001")
    assert spec.tasks[0].depends_on == ()
    assert spec.tasks[1].task_id == TaskId("TASK-002")
    assert spec.tasks[1].depends_on == (TaskId("TASK-001"),)


def test_parser_extracts_acceptance_criteria() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)

    task1 = spec.tasks[0]
    assert len(task1.acceptance_criteria) == _EXPECTED_AC_COUNT
    assert task1.acceptance_criteria[0] == AcceptanceCriterion(
        ac_id="AC-001", description="First criterion"
    )


def test_parser_extracts_validation_commands() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)

    task1 = spec.tasks[0]
    assert len(task1.validation_commands) == 1
    assert task1.validation_commands[0] == ValidationCommand(
        args=("uv", "run", "pytest", "tests/test_foo.py", "-q")
    )


def test_parser_rejects_missing_frontmatter() -> None:
    with pytest.raises(SpecParseError, match="missing frontmatter"):
        SpecParser().parse("# No frontmatter here\n")


def test_parser_rejects_unknown_frontmatter_key() -> None:
    text = "---\nspec_id: X\nschema_version: 1\ntitle: T\nunknown: bad\n---\n"
    with pytest.raises(SpecParseError, match="unknown key"):
        SpecParser().parse(text)


def test_parser_rejects_duplicate_frontmatter_key() -> None:
    text = "---\nspec_id: X\nspec_id: Y\nschema_version: 1\ntitle: T\n---\n"
    with pytest.raises(SpecParseError, match="duplicate key"):
        SpecParser().parse(text)


def test_parser_rejects_missing_required_frontmatter_key() -> None:
    text = "---\nspec_id: X\nschema_version: 1\n---\n"
    with pytest.raises(SpecParseError, match="missing required key"):
        SpecParser().parse(text)


def test_parser_rejects_non_integer_schema_version() -> None:
    text = "---\nspec_id: X\nschema_version: abc\ntitle: T\n---\n"
    with pytest.raises(SpecParseError, match="schema_version must be integer"):
        SpecParser().parse(text)


def test_parser_rejects_oversized_spec() -> None:
    text = "---\nspec_id: X\nschema_version: 1\ntitle: T\n---\n" + "x" * 1_048_577
    with pytest.raises(SpecParseError, match="max_spec_bytes"):
        SpecParser().parse(text)


def test_validator_passes_valid_spec() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)
    report = SpecValidator().validate(spec)

    assert report.valid is True
    assert report.errors == ()
    assert report.spec is not None


def test_validator_rejects_wrong_schema_version() -> None:
    spec = SoftwareSpec(spec_id="X", schema_version=2, title="T", tasks=())
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "INVALID_SCHEMA_VERSION" for e in report.errors)


def test_validator_rejects_duplicate_task_ids() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=("src/a.py",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task, task))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "DUPLICATE_TASK_ID" for e in report.errors)


def test_validator_rejects_duplicate_ac_ids() -> None:
    ac = AcceptanceCriterion("AC-001", "desc")
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=("src/a.py",),
        acceptance_criteria=(ac, ac),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "DUPLICATE_AC_ID" for e in report.errors)


def test_validator_rejects_empty_allowed_paths() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=(),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "EMPTY_ALLOWED_PATHS" for e in report.errors)


def test_validator_rejects_shell_string_in_command() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=("src/a.py",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok | rm -rf /")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "SHELL_STRING_IN_COMMAND" for e in report.errors)


def test_validator_rejects_dependency_cycle() -> None:
    task_a = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(TaskId("TASK-002"),),
        allowed_paths=("src/a.py",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    task_b = TaskSpec(
        task_id=TaskId("TASK-002"),
        title="B",
        depends_on=(TaskId("TASK-001"),),
        allowed_paths=("src/b.py",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task_a, task_b))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "DEPENDENCY_CYCLE" for e in report.errors)


def test_validator_rejects_unknown_dependency() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(TaskId("TASK-999"),),
        allowed_paths=("src/a.py",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "UNKNOWN_DEPENDENCY" for e in report.errors)


def test_validator_rejects_unsafe_path_traversal() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=("../../../etc/passwd",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "UNSAFE_PATH" for e in report.errors)


def test_validator_rejects_absolute_path() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=("/etc/passwd",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "UNSAFE_PATH" for e in report.errors)


def test_validator_selects_task_by_id() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)
    report = SpecValidator().validate(spec, task_id="TASK-001")

    assert report.valid is True


def test_validator_rejects_unknown_task_id() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)
    report = SpecValidator().validate(spec, task_id="TASK-999")

    assert report.valid is False
    assert any(e.code == "TASK_NOT_FOUND" for e in report.errors)


def test_validate_has_no_external_effects(tmp_path: Path) -> None:
    """AC-003: validation never creates .aifactory, worktree or external calls."""
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(VALID_SPEC_TEXT, encoding="utf-8")

    aifactory_dir = tmp_path / ".aifactory"
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    subprocess_calls: list[str] = []
    original_run = subprocess.run

    def spy_run(*args: object, **kwargs: object) -> object:
        subprocess_calls.append(str(args))
        return original_run(*args, **kwargs)  # type: ignore[arg-type]

    try:
        parser = SpecParser()
        text = spec_file.read_text(encoding="utf-8")
        spec = parser.parse(text)
        with patch("subprocess.run", side_effect=spy_run):
            report = SpecValidator().validate(spec)
    finally:
        os.chdir(original_cwd)

    assert report.valid is True
    assert not aifactory_dir.exists()
    assert len(subprocess_calls) == 0


def test_parser_handles_empty_depends_on_section() -> None:
    text = """\
---
spec_id: SPEC-001
schema_version: 1
title: Test
---

## TASK-001 — Solo task

**Depends on:**

**Allowed paths:**
- src/a.py

**Acceptance criteria:**
- AC-001 — Works

**Validation commands:**
- uv run pytest -q
"""
    spec = SpecParser().parse(text)
    assert spec.tasks[0].depends_on == ()


def test_validator_rejects_empty_acceptance_criteria() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=("src/a.py",),
        acceptance_criteria=(),
        validation_commands=(ValidationCommand(("echo", "ok")),),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "EMPTY_ACCEPTANCE_CRITERIA" for e in report.errors)


def test_validator_rejects_empty_validation_commands() -> None:
    task = TaskSpec(
        task_id=TaskId("TASK-001"),
        title="A",
        depends_on=(),
        allowed_paths=("src/a.py",),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "desc"),),
        validation_commands=(),
    )
    spec = SoftwareSpec(spec_id="X", schema_version=1, title="T", tasks=(task,))
    report = SpecValidator().validate(spec)

    assert report.valid is False
    assert any(e.code == "EMPTY_VALIDATION_COMMANDS" for e in report.errors)


def test_canonical_json_is_sorted_and_deterministic() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)

    result_a = canonical_json(spec)
    result_b = canonical_json(spec)

    assert result_a == result_b
    parsed = json.loads(result_a)
    keys = list(parsed.keys())
    assert keys == sorted(keys)


def test_spec_models_are_immutable() -> None:
    parser = SpecParser()
    spec = parser.parse(VALID_SPEC_TEXT)

    with pytest.raises(AttributeError):
        spec.spec_id = "hacked"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        spec.tasks[0].title = "hacked"  # type: ignore[misc]
