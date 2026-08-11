# SPEC Contract v1

## Overview

The Software SPEC is a Markdown document with YAML-like frontmatter that describes
a set of tasks, their dependencies, acceptance criteria and validation commands.
It is parsed by `SpecParser` (pure, no I/O) and validated by `SpecValidator` (pure, no I/O).

## Format

```markdown
---
spec_id: SPEC-001
schema_version: 1
title: Human-readable title
---

# Title

## TASK-001 — Task title

**Depends on:**

**Allowed paths:**
- src/foo.py
- tests/test_foo.py

**Acceptance criteria:**
- AC-001 — Criterion description
- AC-002 — Another criterion

**Validation commands:**
- uv run pytest tests/test_foo.py -q
```

## Frontmatter fields

| Field | Type | Required | Description |
|---|---|---|---|
| `spec_id` | string | yes | Unique SPEC identifier |
| `schema_version` | integer | yes | Must be `1` |
| `title` | string | yes | Human-readable title |

## Task sections

Each `## TASK-NNN — Title` heading starts a new task. The following labeled
sections are recognized within each task:

- **Depends on:** — list of `TASK-NNN` dependencies (may be empty)
- **Allowed paths:** — list of relative file paths the task may modify
- **Acceptance criteria:** — list of `AC-NNN — description` items
- **Validation commands:** — list of commands as argument arrays

## Limits

| Limit | Value |
|---|---|
| `max_spec_bytes` | 1,048,576 |
| `max_tasks` | 200 |
| `max_dependency_depth` | 50 |

## Validation rules

1. `schema_version` must equal `1`.
2. Task IDs match `TASK-\d{3,}`.
3. No duplicate task IDs.
4. AC IDs match `AC-\d{3,}` and are unique within each task.
5. Each task has at least one allowed path, acceptance criterion and validation command.
6. Paths are relative (no leading `/`, no `..` components).
7. Validation commands are argument arrays — shell metacharacters are rejected.
8. Dependencies form a DAG (no cycles).
9. Dependency depth does not exceed 50.
10. All dependency references point to existing tasks.

## CLI usage

```bash
aif spec validate PATH [--task TASK-ID] [--json]
```

Exit codes: `0` = valid, `2` = invalid input or contract violation.
