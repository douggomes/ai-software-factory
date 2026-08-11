#!/usr/bin/env python3
"""Validate AI-executable task contracts using only the Python standard library."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / "docs" / "planejamento"
TASK_FILE = re.compile(r"task(?P<number>[1-9][0-9]*)\.md$")
TASK_ID = re.compile(r"TASK-(?P<number>[0-9]{3})$")
SHA = re.compile(r"[0-9a-f]{40}$")
LINK = re.compile(r"\[[^]]+\]\((?!https?://|#)([^)]+\.md)(?:#[^)]*)?\)")
AC = re.compile(r"^- \[[ x]\] \*\*(AC-[0-9]{3})\*\* — ", re.MULTILINE)
MATRIX_AC = re.compile(r"^\| (AC-[0-9]{3}) \| `[^`]+` \| [^|]+ \| [^|]+ \|$", re.MULTILINE)
UNCHECKED_ITEM = re.compile(r"^- \[ \]", re.MULTILINE)
TEST_REFERENCE = re.compile(r"(?P<path>tests/[\w./-]+\.py)(?:::(?P<nodeid>[\w:]+))?")

REQUIRED_FIELDS = {
    "title",
    "task_id",
    "release",
    "status",
    "depends_on",
    "baseline_commit",
    "risk_level",
}
REQUIRED_SECTIONS = (
    "Valor entregue",
    "Definition of Ready",
    "Precondições",
    "Arquivos permitidos",
    "Arquivos proibidos",
    "Interfaces e contratos",
    "Defaults e decisões fechadas",
    "Passos de implementação",
    "Riscos e controles",
    "Critérios de aceite",
    "Matriz de verificação",
    "Validação manual no terminal",
    "Fora de escopo",
    "Evidência de conclusão",
)
ALLOWED_STATUS = {"planned", "ready", "in_progress", "blocked", "done"}
ALLOWED_RISK = {"low", "medium", "high", "critical"}
MIN_ACCEPTANCE_CRITERIA = 2


@dataclass(frozen=True)
class Task:
    path: Path
    text: str
    fields: dict[str, str]
    dependencies: tuple[str, ...]

    @property
    def task_id(self) -> str:
        return self.fields.get("task_id", "")


def frontmatter(text: str, path: Path, errors: list[str]) -> dict[str, str]:
    if not text.startswith("---\n"):
        errors.append(f"{path}: frontmatter ausente")
        return {}
    try:
        block = text.split("---\n", 2)[1]
    except IndexError:
        errors.append(f"{path}: frontmatter não fechado")
        return {}
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    missing = REQUIRED_FIELDS - fields.keys()
    if missing:
        errors.append(f"{path}: campos ausentes: {', '.join(sorted(missing))}")
    return fields


def dependencies(raw: str) -> tuple[str, ...]:
    return tuple(re.findall(r"TASK-[0-9]{3}", raw))


def section(text: str, name: str) -> str:
    match = re.search(
        rf"^## {re.escape(name)}\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() if match else ""


def load_tasks(errors: list[str]) -> list[Task]:
    tasks: list[Task] = []
    for path in sorted(PLANNING.glob("task*.md")):
        match = TASK_FILE.fullmatch(path.name)
        if not match:
            continue
        text = path.read_text(encoding="utf-8")
        fields = frontmatter(text, path, errors)
        tasks.append(Task(path, text, fields, dependencies(fields.get("depends_on", ""))))
    return tasks


def validate_identity(task: Task, errors: list[str]) -> None:
    file_match = TASK_FILE.fullmatch(task.path.name)
    id_match = TASK_ID.fullmatch(task.task_id)
    if not file_match or not id_match:
        errors.append(f"{task.path}: filename/task_id inválido")
    elif int(file_match["number"]) != int(id_match["number"]):
        errors.append(f"{task.path}: filename não corresponde a {task.task_id}")


def validate_state(task: Task, errors: list[str]) -> None:
    status = task.fields.get("status", "")
    if status not in ALLOWED_STATUS:
        errors.append(f"{task.path}: status inválido: {status}")
    risk = task.fields.get("risk_level", "")
    if risk not in ALLOWED_RISK:
        errors.append(f"{task.path}: risk_level inválido: {risk}")

    baseline = task.fields.get("baseline_commit", "")
    if status == "planned" and baseline != "TO_BE_PINNED":
        errors.append(f"{task.path}: task planned deve usar TO_BE_PINNED")
        return
    if status == "planned":
        return
    task_one_baseline = task.task_id == "TASK-001" and baseline == "UNBORN"
    if not task_one_baseline and not SHA.fullmatch(baseline):
        errors.append(f"{task.path}: task não planejada exige baseline SHA")


def validate_sections_and_paths(task: Task, errors: list[str]) -> None:
    for name in REQUIRED_SECTIONS:
        body = section(task.text, name)
        if not body:
            errors.append(f"{task.path}: seção ausente/vazia: {name}")

    allowed = section(task.text, "Arquivos permitidos")
    forbidden = section(task.text, "Arquivos proibidos")
    if not re.search(r"^- `[^`]+`", allowed, re.MULTILINE):
        errors.append(f"{task.path}: Arquivos permitidos sem path explícito")
    if not re.search(r"^- `[^`]+`", forbidden, re.MULTILINE):
        errors.append(f"{task.path}: Arquivos proibidos sem path explícito")


def validate_acceptance_mapping(task: Task, errors: list[str]) -> None:
    criteria = AC.findall(section(task.text, "Critérios de aceite"))
    matrix = MATRIX_AC.findall(section(task.text, "Matriz de verificação"))
    if len(criteria) < MIN_ACCEPTANCE_CRITERIA:
        errors.append(f"{task.path}: mínimo de dois critérios de aceite")
    if len(criteria) != len(set(criteria)):
        errors.append(f"{task.path}: AC duplicado")
    if set(criteria) != set(matrix) or len(matrix) != len(criteria):
        errors.append(
            f"{task.path}: matriz não cobre ACs exatamente: critérios={criteria}, matriz={matrix}"
        )

    manual = section(task.text, "Validação manual no terminal")
    commands = re.findall(r"^[0-9]+\. `[^`]+`$", manual, re.MULTILINE)
    expectations = re.findall(r"^   Esperado: .+$", manual, re.MULTILINE)
    if not commands or len(commands) != len(expectations):
        errors.append(f"{task.path}: validação manual exige pares numerados comando/Esperado")


def validate_normative_references(task: Task, errors: list[str]) -> None:
    references = ("AGENTS.md", "engineering-standards.md", "security-review.md")
    missing = [reference for reference in references if reference not in task.text]
    if missing:
        errors.append(f"{task.path}: referências normativas ausentes: {missing}")


def _ast_node_exists(body: list[ast.stmt], parts: tuple[str, ...]) -> bool:
    """Walk pytest node-id segments (Class::method) through a parsed test file."""
    if not parts:
        return True
    name, rest = parts[0], parts[1:]
    for node in body:
        is_def = isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        if is_def and node.name == name:
            return _ast_node_exists(getattr(node, "body", []), rest)
    return False


def validate_test_references(task: Task, errors: list[str]) -> None:
    """Every `path.py::node::id` referenced by an implemented task must resolve.

    A referenced test *file* that does not exist yet is not an error — the
    task may still be `planned`. But once the file exists, a node id inside
    it that cannot be found is a broken normative command (QA-003-001).
    """
    seen: set[str] = set()
    for match in TEST_REFERENCE.finditer(task.text):
        rel_path = match.group("path")
        node_id = match.group("nodeid")
        if node_id is None:
            continue
        key = f"{rel_path}::{node_id}"
        if key in seen:
            continue
        seen.add(key)
        test_path = ROOT / rel_path
        if not test_path.is_file():
            continue
        try:
            tree = ast.parse(test_path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            errors.append(f"{task.path}: não foi possível analisar {rel_path}: {error}")
            continue
        if not _ast_node_exists(tree.body, tuple(node_id.split("::"))):
            errors.append(f"{task.path}: nó de teste inexistente: {key}")


def validate_done_checkboxes(task: Task, errors: list[str]) -> None:
    """A task marked done cannot leave its own gates unchecked (QA-GOV-001)."""
    if task.fields.get("status") != "done":
        return
    for section_name in ("Definition of Ready", "Critérios de aceite"):
        unchecked = len(UNCHECKED_ITEM.findall(section(task.text, section_name)))
        if unchecked:
            errors.append(
                f"{task.path}: status done mas '{section_name}' tem "
                f"{unchecked} item(ns) não marcado(s)"
            )


def validate_task(task: Task, errors: list[str]) -> None:
    validate_identity(task, errors)
    validate_state(task, errors)
    validate_sections_and_paths(task, errors)
    validate_acceptance_mapping(task, errors)
    validate_normative_references(task, errors)
    validate_test_references(task, errors)
    validate_done_checkboxes(task, errors)


def validate_dependencies(by_id: dict[str, Task], errors: list[str]) -> None:
    for task in by_id.values():
        missing = [dependency for dependency in task.dependencies if dependency not in by_id]
        if missing:
            errors.append(f"{task.path}: dependências inexistentes {missing}")
        if task.task_id in task.dependencies:
            errors.append(f"{task.path}: dependência de si mesma")


def validate_cycles(by_id: dict[str, Task], errors: list[str]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            errors.append(f"ciclo de dependência em {task_id}")
            return
        if task_id in visited or task_id not in by_id:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].dependencies:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)


def validate_ready_task(by_id: dict[str, Task], errors: list[str]) -> None:
    ready = [task for task in by_id.values() if task.fields.get("status") == "ready"]
    if len(ready) > 1:
        errors.append(
            f"pode existir no máximo uma task ready; encontrado: {[task.task_id for task in ready]}"
        )
        return
    if not ready:
        return
    task = ready[0]
    incomplete = [
        dependency
        for dependency in task.dependencies
        if by_id[dependency].fields.get("status") != "done"
    ]
    if incomplete:
        errors.append(f"{task.path}: dependências não concluídas: {incomplete}")


def validate_graph(tasks: list[Task], errors: list[str]) -> None:
    by_id = {task.task_id: task for task in tasks}
    if len(by_id) != len(tasks):
        errors.append("task_id duplicado")
        return
    validate_dependencies(by_id, errors)
    validate_cycles(by_id, errors)
    validate_ready_task(by_id, errors)


def validate_links(errors: list[str]) -> None:
    for path in [ROOT / "AGENTS.md", ROOT / "README.md", *PLANNING.glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        for raw_target in LINK.findall(text):
            target = (path.parent / raw_target).resolve()
            if not target.is_file():
                errors.append(f"{path}: link local inexistente: {raw_target}")


def main() -> int:
    errors: list[str] = []
    tasks = load_tasks(errors)
    if not tasks:
        errors.append("nenhuma task encontrada")
    for task in tasks:
        validate_task(task, errors)
    validate_graph(tasks, errors)
    validate_links(errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"FAILED: {len(errors)} erro(s)", file=sys.stderr)
        return 1
    ready = next(
        (task.task_id for task in tasks if task.fields.get("status") == "ready"),
        "none",
    )
    print(f"OK: {len(tasks)} tasks; ready={ready}; contratos e links válidos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
