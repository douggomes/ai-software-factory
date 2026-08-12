from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.validate_tasks import validate_planning_is_versioned  # noqa: E402


def test_planning_tree_cannot_be_ignored(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run(  # noqa: S603 - resolved Git executable in isolated repository
        [git, "init", "-q"],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=True,
    )
    (tmp_path / ".gitignore").write_text("docs/planejamento/\n", encoding="utf-8")

    errors: list[str] = []
    validate_planning_is_versioned(tmp_path, errors)

    assert errors == ["docs/planejamento está ignorado; estado normativo deve ser versionado"]


def test_planning_tree_is_accepted_when_versioned(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run(  # noqa: S603 - resolved Git executable in isolated repository
        [git, "init", "-q"],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=True,
    )

    errors: list[str] = []
    validate_planning_is_versioned(tmp_path, errors)

    assert errors == []
