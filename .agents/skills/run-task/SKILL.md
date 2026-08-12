---
name: run-task
description: Execute the repository's single ready task from preflight through a draft pull request. Use when the user asks to implement, continue, or complete an AI Software Factory task under AGENTS.md governance.
---

# Run Task

This skill is only a discovery entrypoint. It grants no authority and defines no workflow of its own.

1. Read `AGENTS.md` completely, then execute its task-selection, scope, security, lifecycle, Git, and evidence sections exactly as written.
2. Read the consolidated plan, the single active task, and every normative document, ADR, contract, command, and manual validation item they reference.
3. For the review step named by `AGENTS.md`, discover the canonical checklists under `.agents/reviewers/`; use their host adapters only to impose read-only execution.
4. If any adapter or this skill conflicts with a canonical source, stop and follow `AGENTS.md`.
