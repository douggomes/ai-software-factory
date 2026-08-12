---
name: new-task
description: Scaffold and validate a new planned TASK-NNN contract from the repository template. Use only when the user explicitly asks to create a task; never invoke it implicitly or activate a task.
---

# New Task

Run this workflow only after an explicit user request to create a task.

1. Read `AGENTS.md`, the plan, `task-template.md`, and `scripts/validate_tasks.py`.
2. Determine the next sequential task ID. Obtain a concrete title, release, dependencies, observable value, closed interfaces/defaults, allowed files, negative security case, acceptance criteria, evidence commands, and manual validation.
3. Scaffold the contract without activating it. This governance operation is executed by the user or by a session explicitly authorized for `new-task`; it is intentionally outside the implementation-task shell hook:

   ```bash
   python3 .agents/skills/new-task/scripts/scaffold_task.py \
     --task-id TASK-NNN \
     --title "Observable result" \
     --release Vx.y \
     --risk-level high \
     --depends-on TASK-NNN
   ```

4. Refine only the new `status: planned` contract and the consolidated plan. Keep `baseline_commit: "TO_BE_PINNED"`; do not mark Definition of Ready or acceptance criteria as complete.
5. Run `python3 scripts/validate_tasks.py`. Report the created files and unresolved decisions.

Never activate the task, pin a baseline, change another task's status, or publish unless the user separately authorizes that governance action.
