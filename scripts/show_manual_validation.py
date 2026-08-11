#!/usr/bin/env python3
"""Print the manual validation instructions for one task contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / "docs" / "planejamento"
TASK_ID = re.compile(r"TASK-[0-9]{3}")
EXPECTED_ARGUMENT_COUNT = 2


def section(text: str, name: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(name)}\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() if match else None


def find_task(task_id: str) -> Path | None:
    for path in sorted(PLANNING.glob("task[0-9]*.md")):
        text = path.read_text(encoding="utf-8")
        if re.search(rf"^task_id: {re.escape(task_id)}$", text, re.MULTILINE):
            return path
    return None


def main(argv: list[str]) -> int:
    if len(argv) != EXPECTED_ARGUMENT_COUNT or not TASK_ID.fullmatch(argv[1].upper()):
        print("Uso: python3 scripts/show_manual_validation.py TASK-NNN", file=sys.stderr)
        return 2
    task_id = argv[1].upper()
    path = find_task(task_id)
    if path is None:
        print(f"Task não encontrada: {task_id}", file=sys.stderr)
        return 1
    body = section(path.read_text(encoding="utf-8"), "Validação manual no terminal")
    if not body:
        print(f"Task sem instruções de validação manual: {task_id}", file=sys.stderr)
        return 1
    print(f"=== VALIDAÇÃO MANUAL {task_id} ===")
    print(body)
    print(f"=== FIM DA VALIDAÇÃO MANUAL {task_id} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
