#!/usr/bin/env python3
"""Validate AI-executable task contracts using only the Python standard library."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / "planejamento"
TASK_FILE = re.compile(r"task(?P<number>[1-9][0-9]*)\.md$")
TASK_ID = re.compile(r"TASK-(?P<number>[0-9]{3})$")
SHA = re.compile(r"[0-9a-f]{40}$")
LINK = re.compile(r"\[[^]]+\]\((?!https?://|#)([^)]+\.md)(?:#[^)]*)?\)")
AC = re.compile(r"^- \[ \] \*\*(AC-[0-9]{3})\*\* — ", re.MULTILINE)
MATRIX_AC = re.compile(r"^\| (AC-[0-9]{3}) \| `[^`]+` \| [^|]+ \| [^|]+ \|$", re.MULTILINE)

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
    "Fora de escopo",
    "Evidência de conclusão",
)
ALLOWED_STATUS = {"planned", "ready", "in_progress", "blocked", "done"}
ALLOWED_RISK = {"low", "medium", "high", "critical"}


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


def validate_task(task: Task, errors: list[str]) -> None:
    file_match = TASK_FILE.fullmatch(task.path.name)
    id_match = TASK_ID.fullmatch(task.task_id)
    if not file_match or not id_match:
        errors.append(f"{task.path}: filename/task_id inválido")
    elif int(file_match["number"]) != int(id_match["number"]):
        errors.append(f"{task.path}: filename não corresponde a {task.task_id}")

    status = task.fields.get("status", "")
    if status not in ALLOWED_STATUS:
        errors.append(f"{task.path}: status inválido: {status}")
    risk = task.fields.get("risk_level", "")
    if risk not in ALLOWED_RISK:
        errors.append(f"{task.path}: risk_level inválido: {risk}")

    baseline = task.fields.get("baseline_commit", "")
    if status == "ready":
        if task.task_id == "TASK-001":
            if baseline != "UNBORN" and not SHA.fullmatch(baseline):
                errors.append(f"{task.path}: baseline ready deve ser UNBORN ou SHA")
        elif not SHA.fullmatch(baseline):
            errors.append(f"{task.path}: task ready exige baseline SHA de 40 caracteres")
    elif status == "planned" and baseline != "TO_BE_PINNED":
        errors.append(f"{task.path}: task planned deve usar TO_BE_PINNED")
    elif status in {"in_progress", "blocked", "done"}:
        if task.task_id == "TASK-001":
            if baseline != "UNBORN" and not SHA.fullmatch(baseline):
                errors.append(f"{task.path}: baseline ativo/concluído inválido")
        elif not SHA.fullmatch(baseline):
            errors.append(f"{task.path}: task ativa/concluída exige baseline SHA")

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

    criteria = AC.findall(section(task.text, "Critérios de aceite"))
    matrix = MATRIX_AC.findall(section(task.text, "Matriz de verificação"))
    if len(criteria) < 2:
        errors.append(f"{task.path}: mínimo de dois critérios de aceite")
    if len(criteria) != len(set(criteria)):
        errors.append(f"{task.path}: AC duplicado")
    if set(criteria) != set(matrix) or len(matrix) != len(criteria):
        errors.append(
            f"{task.path}: matriz não cobre ACs exatamente: critérios={criteria}, matriz={matrix}"
        )

    if "AGENTS.md" not in task.text or "engineering-standards.md" not in task.text:
        errors.append(f"{task.path}: referências normativas ausentes")


def validate_graph(tasks: list[Task], errors: list[str]) -> None:
    by_id = {task.task_id: task for task in tasks}
    if len(by_id) != len(tasks):
        errors.append("task_id duplicado")
    for task in tasks:
        for dependency in task.dependencies:
            if dependency not in by_id:
                errors.append(f"{task.path}: dependência inexistente {dependency}")
            elif dependency == task.task_id:
                errors.append(f"{task.path}: dependência de si mesma")

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

    ready = [task for task in tasks if task.fields.get("status") == "ready"]
    if len(ready) != 1:
        errors.append(
            f"deve existir exatamente uma task ready; encontrado: {[task.task_id for task in ready]}"
        )
    else:
        for dependency in ready[0].dependencies:
            dependency_status = by_id[dependency].fields.get("status")
            if dependency_status != "done":
                errors.append(
                    f"{ready[0].path}: dependência {dependency} não está done: {dependency_status}"
                )


def validate_links(errors: list[str]) -> None:
    for path in [ROOT / "AGENTS.md", *PLANNING.glob("*.md")]:
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
    ready = next(task.task_id for task in tasks if task.fields.get("status") == "ready")
    print(f"OK: {len(tasks)} tasks; ready={ready}; contratos e links válidos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
