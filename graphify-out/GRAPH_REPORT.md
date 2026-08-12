# Graph Report - .  (2026-08-12)

## Corpus Check
- 127 files · ~67,599 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1437 nodes · 3531 edges · 86 communities (74 shown, 12 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 519 edges (avg confidence: 0.54)
- Token cost: 411,105 input · 0 output

## Community Hubs (Navigation)
- Git Worktree Isolation
- CLI Entry Point & Doctor
- Filesystem Artifact Store
- Portable Automation Hook
- SQLite Connection & Migrations
- Persistence Schema & Adapters
- TASK-001/002 Bootstrap & Spec Validate
- Run/Task Persistence Correlation
- State Machine Transition Tests
- Run Status Queries & Events
- RunStore Port & State Machine
- SpecParser Abuse Hardening
- Task Contract Validator Script
- SpecValidator & Parser Tests
- SQLiteRunStore Lifecycle Tests
- SpecValidator Checks
- Asyncio Process Runner
- ADRs & Core Domain Ports
- TASK-010/011 Worker Routing & Circuit Breaker
- Process Request/Policy Models
- Package Init & Doctor Tests
- AGENTS.md Governance Policy
- Domain IDs & Task Execution
- Spec Domain Models
- Task Scaffold Script
- Task Execution Persistence Events
- Process Result Models
- SPEC Schema Properties
- Stream Capture & Redaction
- Frontmatter Parsing
- Setup Validation Script
- Brainstorming & Security Decisions
- TASK-016 Structured Review
- SPEC Schema AC Fields
- TASK-014/015 V0.1 Release Qualification
- TASK-028/029 Cancellation & Chaos
- SPEC Schema Root Fields
- Security Review Findings
- TASK-018/019 Human Gate & Commit
- TASK-021/022 Local Planner
- TASK-026/027 Dataset & Hidden Tests
- TASK-009 Orchestrator Offline Run
- SPEC Schema Task Array
- SPEC Schema Task Fields
- Asyncio Runner Artifact Persist
- Failure Taxonomy
- Process Runner Tests
- TASK-007 Worktree Manager
- Reviewer Checklist & SOLID
- TASK-032 Cross-Host Portability
- SPEC Schema Task Object
- Spec Parser Task Builder
- TASK-021/023 Planner MCP Tools
- TASK-030 Concurrent DAG Execution
- TASK-031 Benchmark & Release Dossier
- TASK-005 Artifact Store Contract
- TASK-008 Validation Snapshot Gates
- TASK-019/025 Context Builder & Benchmark
- TASK-024/026 Observability
- TASK-006 Process Runner Policy
- SPEC Contract Documentation
- SPEC Schema Pattern Fields
- Portable Skills Tests
- Engineering Standards & DoD
- TASK-020 Claude Code Adapter
- SPEC Schema Description Fields
- Process Runner Contract Tests
- Cross-Task Closed Decisions
- SPEC Schema Tasks Array
- Manual Validation Script
- Reviewer Portability Tests
- CLI Exit Code Tests
- ADR-0003 Worktree Isolation Rationale
- SPEC Schema Task ID Field
- Dev-Agent Package Init
- Persistence Adapters Package Init
- Application Package Init
- Core Domain Package Init
- Ports Package Init
- Contract Tests Package Init
- Persistence Contract Tests Init
- Process Contract Tests Init
- Workspace Contract Tests Init
- Project Metadata

## God Nodes (most connected - your core abstractions)
1. `RunId` - 112 edges
2. `DomainEvent` - 67 edges
3. `TaskId` - 61 edges
4. `SpecValidator` - 53 edges
5. `SoftwareSpec` - 52 edges
6. `FilesystemArtifactStore` - 50 edges
7. `SpecParser` - 47 edges
8. `TestAllTransitionsAndTerminalInvariants` - 43 edges
9. `SQLiteRunStore` - 41 edges
10. `TaskExecution` - 41 edges

## Surprising Connections (you probably didn't know these)
- `Mandatory Engineering Rules (SOLID/Ports)` --conceptually_related_to--> `Engineering Standards Norm (Clean Code/SOLID/DoD)`  [INFERRED]
  AGENTS.md → docs/planejamento/engineering-standards.md
- `Mandatory Task Lifecycle (9 Steps)` --conceptually_related_to--> `AI Software Factory Implementation Plan`  [INFERRED]
  AGENTS.md → docs/planejamento/plan.md
- `Git and Publication Rules` --conceptually_related_to--> `AI Software Factory Implementation Plan`  [INFERRED]
  AGENTS.md → docs/planejamento/plan.md
- `TASK-030 — Scheduler DAG com paralelismo isolado` --references--> `Test layout (unit, contract, integration, security, chaos)`  [INFERRED]
  docs/planejamento/task30.md → tests/README.md
- `Versioned schemas` --semantically_similar_to--> `Versioned prompts (hashable, separated from untrusted content)`  [INFERRED] [semantically similar]
  schemas/README.md → prompts/README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Portable Read-Only Reviewer Pattern (Canonical + Claude Host)** — agents_reviewers_architecture_boundary_reviewer_checklist, agents_reviewers_security_reviewer_checklist, claude_agents_architecture_boundary_reviewer_adapter, claude_agents_security_reviewer_adapter [INFERRED 0.85]
- **New-Task Governance Capability Across Skill and Host Bindings** — agents_skills_new_task_skill_workflow, agents_skills_new_task_agents_openai_interface, claude_skills_new_task_skill_adapter, agents_agent_agnostic_automation [INFERRED 0.85]
- **Task Contract Lifecycle Spanning Template, Plan, and AGENTS.md** — docs_planejamento_task_template_overview, docs_planejamento_plan_overview, agents_governance_rules, docs_planejamento_engineering_standards_overview [INFERRED 0.85]
- **AgentWorker Contract Adapters (OpenCode, Codex, Claude Code)** — docs_planejamento_task13_opencode_adapter, docs_planejamento_task15_codex_adapter, docs_planejamento_task20_claude_code_adapter [INFERRED 0.85]
- **Bounded Recovery Budget Pattern (Circuit Breaker, Continuation, Repair)** — docs_planejamento_task11_circuit_breaker, docs_planejamento_task12_continuation_package, docs_planejamento_task17_repair_loop [INFERRED 0.75]
- **Fail-Closed Unknown Handling Across Failure Taxonomy, Circuit Breaker, and Recovery** — docs_planejamento_task10_task_010, docs_planejamento_task11_task_011, docs_planejamento_task27_task_027 [INFERRED 0.75]
- **Versioned artifact governance pattern (migrations, prompts, schemas)** — migrations_readme_migration_versioning_policy, prompts_readme_versioned_prompts, schemas_readme_versioned_schemas [INFERRED 0.75]
- **Ledger integrity contract, defect discovery, and remediation loop** — docs_planejamento_task4_task_004, docs_reports_qa_tasks_001_004_2026_08_11_qa_004_001, docs_reports_qa_tasks_001_004_2026_08_11_remediation_addendum, migrations_readme_migration_versioning_policy [INFERRED 0.85]

## Communities (86 total, 12 thin omitted)

### Community 0 - "Git Worktree Isolation"
Cohesion: 0.07
Nodes (69): _acquire_lock(), _assert_no_symlinks(), _assert_workspace_paths(), _canonical_directory(), _changed_files(), _decode_line(), _decode_text(), _ensure_directory_entry() (+61 more)

### Community 1 - "CLI Entry Point & Doctor"
Cohesion: 0.06
Nodes (77): Namespace, _assert_real_directory(), _bounded_real_directories(), build_doctor_report(), build_parser(), _canonical_cli_directory(), default_probes(), _discover_workspace_paths() (+69 more)

### Community 2 - "Filesystem Artifact Store"
Cohesion: 0.07
Nodes (45): OSError, _decode_json_object(), ensure_artifact_store(), FilesystemArtifactStore, AsyncEngine, Path, stat_result, Filesystem ArtifactStore and the SQLite event projection adapter. Artifact… (+37 more)

### Community 3 - "Portable Automation Hook"
Cohesion: 0.12
Nodes (57): BinaryIO, audit_changed_scope(), _authorized_activation(), _bounded_quality_process(), _candidate_path(), _contains_sensitive_reference(), _direct_paths(), evaluate_pre() (+49 more)

### Community 4 - "SQLite Connection & Migrations"
Cohesion: 0.05
Nodes (45): AsyncConnection, Connection, _begin_transaction(), _configure_connection(), _load_migrations(), Any, Path, Split a migration file into top-level statements. Aware of ``--`` line comments… (+37 more)

### Community 5 - "Persistence Schema & Adapters"
Cohesion: 0.09
Nodes (30): Persistence adapters package., SQLAlchemy schema definitions for the SQLite persistence layer. Tables are…, SQLite adapter for RunStore — async persistence with WAL and transactions.…, EventType, Enum, Domain events — immutable records of significant occurrences. Events are…, Types of domain events., Immutable value objects for domain identifiers. These are strongly-typed, non-… (+22 more)

### Community 6 - "TASK-001/002 Bootstrap & Spec Validate"
Cohesion: 0.06
Nodes (44): TASK-001 Critérios de aceite, aif doctor --json, aif --version, Settings.load(path: Path | None) -> Settings, TASK-001 — Bootstrap reproduzível e diagnóstico offline, TASK-002 Critérios de aceite, aif spec validate PATH [--task ID] [--json], SpecParser.parse(text: str) -> SoftwareSpec (+36 more)

### Community 7 - "Run/Task Persistence Correlation"
Cohesion: 0.08
Nodes (24): TaskId, Persist a new run and its creation event atomically., Apply a state transition with optimistic version check. Identity is the…, Load a single task execution by run and task IDs., _require_run_correlation(), _require_transition_correlation(), Unique identifier for a factory run., RunId (+16 more)

### Community 8 - "State Machine Transition Tests"
Cohesion: 0.09
Nodes (5): all_transitions(), Return a copy of the complete transition table., _make_event(), AC-001: 100% of the transition table is exercised., TestAllTransitionsAndTerminalInvariants

### Community 9 - "Run Status Queries & Events"
Cohesion: 0.11
Nodes (29): Reconstruct run state from the persistence layer., event_to_json_dict(), EventLogReader, format_events_ndjson(), format_run_status_json(), Protocol, Read-only queries for run status and deterministic event export. Status and…, Serialize status with stable key order and formatting. (+21 more)

### Community 10 - "RunStore Port & State Machine"
Cohesion: 0.14
Nodes (34): Result of a valid state transition., Compute the next state for a given stage and event. Pure function — never…, Transition, Protocol, Apply a state transition with optimistic version check. Identity is the…, Release any resources held by the store., Protocol for run state and event persistence. Implementations must guarantee…, RunStore (+26 more)

### Community 11 - "SpecParser Abuse Hardening"
Cohesion: 0.10
Nodes (26): Stateless, pure parser — no I/O, no global state., SpecParser, Risk control: parser rejects hostile frontmatter and traversal., TestParserAbuse, Path, Unit tests for SPEC parser and validator — golden, canonical and no-effects., AC-003: validation never creates .aifactory, worktree or external calls., AC-001: valid SPEC produces identical canonical JSON across runs. (+18 more)

### Community 12 - "Task Contract Validator Script"
Cohesion: 0.13
Nodes (30): _ast_node_exists(), dependencies(), frontmatter(), load_tasks(), main(), Path, Walk pytest node-id segments (Class::method) through a parsed test file., Every `path.py::node::id` referenced by an implemented task must resolve. A… (+22 more)

### Community 13 - "SpecValidator & Parser Tests"
Cohesion: 0.17
Nodes (15): Stateless, pure validator — no I/O, no global state., SpecValidator, _make_spec(), _make_task(), parametrize, Property-based and abuse tests for the SPEC parser and validator. AC-002:…, TestCycleDetection, TestDAGValidation (+7 more)

### Community 14 - "SQLiteRunStore Lifecycle Tests"
Cohesion: 0.09
Nodes (28): AsyncEngine, SQLite-backed RunStore implementation. Uses WAL mode, foreign keys and…, Release the engine and connections., SQLiteRunStore, _make_event(), _make_run(), _make_task_execution(), parametrize (+20 more)

### Community 15 - "SpecValidator Checks"
Cohesion: 0.21
Nodes (22): _check_acceptance_criteria(), _check_allowed_paths(), _check_dependency_cycles(), _check_dependency_depth(), _check_dependency_references(), _check_duplicate_tasks(), _check_schema_version(), _check_task_count() (+14 more)

### Community 16 - "Asyncio Process Runner"
Cohesion: 0.18
Nodes (23): Process, _authorize_request(), _build_environment(), _canonical_directory(), _canonical_path(), _canonical_regular_file(), _is_within(), _isolation_available() (+15 more)

### Community 17 - "ADRs & Core Domain Ports"
Cohesion: 0.12
Nodes (23): ADR-0001 — Workers Are Coding-Agent CLIs, Not Provider APIs, ADR-0002 — SQLite as Operational Source of Truth, ADR Immutability Policy (docs/adr/README.md), D-003 — Execution Hierarchy, AgentPoolSelector Port, AgentWorker Port, Artifact (Domain Model), ArtifactStore Port (+15 more)

### Community 18 - "TASK-010/011 Worker Routing & Circuit Breaker"
Cohesion: 0.09
Nodes (23): TASK-010 Critérios de aceite, AgentPoolSelector.select(request) -> RoutingDecision, aif workers explain --role ROLE, FailureNormalizer.normalize(error) -> NormalizedFailure, TASK-010 — Taxonomia de falhas e seleção estática de workers, TASK-011 Critérios de aceite, aif workers health, Circuit Breaker para saúde de providers (+15 more)

### Community 19 - "Process Request/Policy Models"
Cohesion: 0.21
Nodes (18): _normalize_request_environment(), _normalize_request_paths(), _normalize_request_policy(), _normalize_request_profile(), ProcessModelError, ProcessPolicy, ProcessRequest, ValueError (+10 more)

### Community 20 - "Package Init & Doctor Tests"
Cohesion: 0.17
Nodes (16): AI Software Factory package shell., _fake_tool_probe(), _make_executable(), CaptureFixture, MonkeyPatch, Path, Integration tests for `aif doctor --json` wired through the real CLI parser., QA-001-001 regression: an invalid factory.toml fails before any probe runs. (+8 more)

### Community 21 - "AGENTS.md Governance Policy"
Cohesion: 0.14
Nodes (20): Agent-Agnostic Automation Policy (4.1), Authority Precedence Order, Change Boundaries (Allowed/Forbidden Files), Failure, Doubt, and Safe-Stop Protocol, Mandatory Final Report Format, Git and Publication Rules, AGENTS.md — Absolute Execution Rules, Mandatory Engineering Rules (SOLID/Ports) (+12 more)

### Community 22 - "Domain IDs & Task Execution"
Cohesion: 0.18
Nodes (8): AttemptId, Unique identifier for a task within a SPEC (TASK-NNN)., Unique identifier for an execution attempt., TaskId, ExecutionAttempt, Single attempt to execute a task (initial, retry, failover, repair)., Value objects are immutable, non-interchangeable and serializable., TestIdentityObjects

### Community 23 - "Spec Domain Models"
Cohesion: 0.25
Nodes (18): AcceptanceCriterion, Strongly-typed task identifier (``TASK-NNN``)., Single acceptance criterion with stable ID and description., Command expressed as an argument array — never a shell string., Full specification of one task inside a Software SPEC., TaskId, TaskSpec, ValidationCommand (+10 more)

### Community 24 - "Task Scaffold Script"
Cohesion: 0.27
Nodes (17): main(), _next_task_number(), _open_trusted_directory(), _parser(), ArgumentParser, Path, ValueError, Raised when a requested task contract is unsafe or inconsistent. (+9 more)

### Community 25 - "Task Execution Persistence Events"
Cohesion: 0.18
Nodes (9): datetime, Persist a new task execution and its event atomically., _require_task_correlation(), DomainEvent, Immutable record of a domain occurrence. Carries correlation IDs (run_id,…, Persist a new task execution and its event atomically. Raises…, Persist a new run and its creation event atomically. Raises…, _seed_run() (+1 more)

### Community 26 - "Process Result Models"
Cohesion: 0.15
Nodes (11): ProcessResult, Sanitized outcome of one process invocation. Raw stdout/stderr never cross this…, Expose the conventional subprocess return code without raw output., Whether the process exited normally with status zero., ProcessIsolationError, ProcessRunner, Protocol, Narrow process execution port. The application depends on this protocol and on… (+3 more)

### Community 27 - "SPEC Schema Properties"
Cohesion: 0.13
Nodes (15): properties, schema_version, spec_id, title, const, description, type, description (+7 more)

### Community 28 - "Stream Capture & Redaction"
Cohesion: 0.15
Nodes (9): Read one pipe to completion while keeping only bounded safe bytes., _redact_bytes(), _StreamCapture, Trust classification of the code that will be executed., TrustProfile, ArtifactKind, Coarse classification of stored artifacts., StreamReader (+1 more)

### Community 29 - "Frontmatter Parsing"
Cohesion: 0.27
Nodes (12): _build_frontmatter_result(), _find_closing_delimiter(), _FrontmatterResult, _parse_frontmatter(), _parse_frontmatter_line(), _parse_tasks(), ValueError, Pure SPEC parser — converts Markdown text into immutable domain models. This… (+4 more)

### Community 30 - "Setup Validation Script"
Cohesion: 0.40
Nodes (13): _frontmatter(), _hook_adapters(), _json(), main(), Path, ValueError, Raised when a host adapter diverges from the canonical configuration., _root() (+5 more)

### Community 31 - "Brainstorming & Security Decisions"
Cohesion: 0.15
Nodes (13): D-001 — Modular Monolith, D-002 — Ports and Adapters, D-004 — Three Complementary Sources of Truth, D-005 — Failover Is Not Repair, D-006 — Layered Security, D-007 — Explainable Routing, D-008 — Configuration and Schema Split, D-009 — Python Compatibility Window (+5 more)

### Community 32 - "TASK-016 Structured Review"
Cohesion: 0.15
Nodes (13): TASK-016 Critérios de aceite, Reviewer.review(request: ReviewRequest) -> ReviewResult, ReviewRequest, ReviewResult v1, Review estruturado por critério, TASK-016 — Reviewer estruturado critério por critério, TASK-017 Critérios de aceite, Repair loop limitado com revalidação (+5 more)

### Community 33 - "SPEC Schema AC Fields"
Cohesion: 0.15
Nodes (13): ac_id, args, description, additionalProperties, required, type, $defs, acceptance_criterion (+5 more)

### Community 34 - "TASK-014/015 V0.1 Release Qualification"
Cohesion: 0.17
Nodes (12): TASK-014 Critérios de aceite, first-run.md, docs/releases/v0.1.md, TASK-014 — Qualificação e release V0.1, tests/release/test_v0_1.py, V0.1 Release Gate, TASK-015 Critérios de aceite, Codex Adapter com sandbox explícito (+4 more)

### Community 35 - "TASK-028/029 Cancellation & Chaos"
Cohesion: 0.17
Nodes (12): TASK-028 Critérios de aceite, CancellationService.cancel(run_id, reason) -> CancellationReport, ChaosPoint, Cancelamento estruturado e chaos hardening, TASK-028 — Cancellation, chaos, hardening e release V1.0, V1.0 dossier, TASK-029 Critérios de aceite, aif route explain (+4 more)

### Community 36 - "SPEC Schema Root Fields"
Cohesion: 0.17
Nodes (11): schema_version, spec_id, tasks, title, additionalProperties, description, $id, required (+3 more)

### Community 37 - "Security Review Findings"
Cohesion: 0.22
Nodes (11): F-01 — Clean Code/SOLID Lacked a Gate, F-02 — No Versioned Threat Model/Baselines, F-03 — Filtered Env Treated as Near-Sandbox, F-05 — No Prompt-Injection/Goal-Hijack Policy, F-07 — Approval Did Not Close TOCTOU, F-08 — DB/Artifact Permissions Undefined, F-09 — MCP Cross-Run/Confused-Deputy Risk Unaddressed, F-10 — Router History Susceptible to Poisoning (+3 more)

### Community 38 - "TASK-018/019 Human Gate & Commit"
Cohesion: 0.18
Nodes (11): TASK-018 Critérios de aceite, aif approve RUN-ID --actor ACTOR, aif reject RUN-ID --actor ACTOR --reason TEXT, CommitService.commit(approval: Approval) -> CommitResult, Human gate e commit seguro, TASK-018 — Human gate, commit seguro e release V0.2, TASK-019 Critérios de aceite, ContextBuilder.build(request: ContextRequest) -> ContextManifest (+3 more)

### Community 39 - "TASK-021/022 Local Planner"
Cohesion: 0.18
Nodes (11): TASK-021 Critérios de aceite, aif doctor planner probe, OllamaPlanner, Planner.plan(request: PlanRequest) -> PlanResult, TASK-021 — Planner Ollama local com structured output, TASK-022 Critérios de aceite, Perfis de execução e fallback determinístico, ExecutionProfile (+3 more)

### Community 40 - "TASK-026/027 Dataset & Hidden Tests"
Cohesion: 0.18
Nodes (11): TASK-026 Critérios de aceite, dataset v0.5, HiddenTestProvider config, TASK-026 — Dataset, hidden tests e release V0.5, V0.5 report, TASK-027 Critérios de aceite, aif diagnose RUN-ID / aif resume RUN-ID, IdempotencyKey (+3 more)

### Community 41 - "TASK-009 Orchestrator Offline Run"
Cohesion: 0.18
Nodes (11): AC-001 — Cenário offline success termina Succeeded somente após todos os gates, AC-002 — Gate falho ou erro inesperado nunca produz sucesso e preserva worktree/evidência, AC-003 — Instrução maliciosa no repo não amplia autoridade do fake/orchestrator, AgentWorker.execute(request) -> AsyncIterator[AgentEvent], FactoryOrchestrator.run_task(command) -> RunReport, fake_worker somente dev/test; worker_authority write no worktree; policy_vs_context separada, RunReport v1 (JSON schema), TASK-009 — Pipeline vertical offline com FakeAgentWorker (+3 more)

### Community 42 - "SPEC Schema Task Array"
Cohesion: 0.20
Nodes (11): items, minItems, type, $ref, acceptance_criteria, validation_commands, properties, items (+3 more)

### Community 43 - "SPEC Schema Task Fields"
Cohesion: 0.18
Nodes (11): description, items, minItems, type, description, items, type, pattern (+3 more)

### Community 44 - "Asyncio Runner Artifact Persist"
Cohesion: 0.22
Nodes (8): AsyncioProcessRunner, ProcessRunner implementation backed by ``asyncio`` and POSIX groups., ArtifactReference, Protocol, Structural reference returned by an artifact adapter., Validated path relative to the run artifact root., ProcessArtifactError, Raised when sanitized process output cannot be persisted.

### Community 45 - "Failure Taxonomy"
Cohesion: 0.25
Nodes (10): FailureCategory, FailureDisposition, NormalizedFailure, Enum, Failure taxonomy — normalized categories for worker and operational failures.…, Normalized failure categories from the domain model., What the system should do in response to a failure., A failure normalized to the domain taxonomy. Immutable record linking a failure… (+2 more)

### Community 46 - "Process Runner Tests"
Cohesion: 0.53
Nodes (10): _fake_executable(), _pid_exists(), asyncio, Path, Integration tests for the secure asyncio ProcessRunner., _request(), test_arguments_are_literal_and_policy_enforced(), test_canary_limits_and_fail_closed() (+2 more)

### Community 47 - "TASK-007 Worktree Manager"
Cohesion: 0.22
Nodes (10): AC-001 — Prepare idempotente cria worktree na base exata e não altera checkout principal, AC-002 — Dois writers não obtêm o mesmo lock e workspace incompatível falha, AC-003 — Traversal, symlink/TOCTOU, path externo e hook malicioso não executam nem são removidos, TASK-007 — Worktree Git isolado e cleanup seguro, WorkspaceManager.clean(workspace) -> None, WorkspaceManager.inspect(workspace) -> WorkspaceSnapshot, WorkspaceManager.prepare(request) -> Workspace, SPEC-TICKET-001 — Implement user authentication module (+2 more)

### Community 48 - "Reviewer Checklist & SOLID"
Cohesion: 0.39
Nodes (9): Architecture Boundary Reviewer Checklist, Claude Architecture Boundary Reviewer Adapter, Clean Code Rules for Python, DIP — Dependency Inversion Principle, ISP — Interface Segregation Principle, LSP — Liskov Substitution Principle, OCP — Open/Closed Principle, Engineering Standards Norm (Clean Code/SOLID/DoD) (+1 more)

### Community 49 - "TASK-032 Cross-Host Portability"
Cohesion: 0.22
Nodes (9): AC-001 — Claude e Codex carregam AGENTS.md e as mesmas skills canônicas sem duplicação do workflow, AC-002 — Payloads equivalentes dos dois hosts produzem a mesma decisão; escape/segredo/shell mutável falham fechados, AC-003 — Reviewers de segurança e arquitetura usam o mesmo checklist, herdam o modelo e não possuem autoridade de escrita, instructions_source AGENTS.md; policy_failure fail-closed exit 2; reviewer_authority read-only, hook.py --host HOST --phase PHASE, new-task/SKILL.md, run-task/SKILL.md, reviewers compartilhados (checklists canônicos read-only) (+1 more)

### Community 50 - "SPEC Schema Task Object"
Cohesion: 0.22
Nodes (9): acceptance_criteria, allowed_paths, depends_on, task_id, validation_commands, task, additionalProperties, required (+1 more)

### Community 52 - "TASK-021/023 Planner MCP Tools"
Cohesion: 0.25
Nodes (8): Planner Ollama local com structured output, TASK-023 Critérios de aceite, factory_get_solution_map / factory_get_git_diff, factory_get_task, factory_get_validation_result(snapshot_id), factory_run_validation(profile: RegisteredProfile), Servidor MCP semântico e isolado, TASK-023 — Servidor MCP semântico e isolado

### Community 53 - "TASK-030 Concurrent DAG Execution"
Cohesion: 0.25
Nodes (8): AC-001 — Duas tasks independentes sobrepõem tempo; dependente inicia somente após aprovação, AC-002 — Uma task nunca tem dois writers e recursos/contexto/MCP/env/artifacts não cruzam tasks, AC-003 — Falha/cancel/saturation segue policy e preserva outcomes; N=1 reproduz baseline serial, aif run SPEC --all --max-concurrency N, RunAggregate, SchedulerPolicy, TASK-030 — Scheduler DAG com paralelismo isolado, TaskScheduler.run(dag, policy) -> RunAggregate

### Community 54 - "TASK-031 Benchmark & Release Dossier"
Cohesion: 0.25
Nodes (8): AC-001 — 20 tasks e repetições geram raw results com média, dispersão, sample size e failure categories, AC-002 — PR suite offline e gates de arquitetura/typing/test/security/supply chain passam em Python 3.13/3.14, AC-003 — Dossier contém SBOM/provenance/checksums/threat-model/rollback/limitations e aprovação humana pendente exata, PR suite (offline unit/contract/infra/E2E/security/chaos), Release dossier (requirement->task->test->evidence; SBOM/build hashes), Release suite (20 tasks uma vez + 5 estratificadas x3), Research suite (opt-in, budget/quota explícitos), TASK-031 — Qualificação ampliada e release V1.1

### Community 55 - "TASK-005 Artifact Store Contract"
Cohesion: 0.25
Nodes (8): AC-001 — Escrita interrompida não publica artifact e overwrite é rejeitado, AC-002 — Symlink, path externo, owner/mode inválido e hash adulterado falham fechados, AC-003 — Status/eventos sobrevivem reinício e export NDJSON é reconstruível byte a byte, SHA-256 hash, mode 0600, create-exclusive, overwrite proibido, ArtifactStore.put(ref, data) -> StoredArtifact, ArtifactStore.read(ref) -> bytes, aif status RUN-ID --json / aif events RUN-ID, TASK-005 — ArtifactStore íntegro e consulta de execução

### Community 56 - "TASK-008 Validation Snapshot Gates"
Cohesion: 0.25
Nodes (8): AC-001 — Mudança fora de scope, segredo ou git diff --check falho bloqueiam snapshot, AC-002 — Profiles executam argv validado no worktree e persistem evidência sanitizada, AC-003 — Reexecução cria snapshot novo e resultado obrigatório falho impede sucesso, Evaluator.run(profile) -> ValidationSnapshot, gate_order scope,diff,secrets,compile,lint,types,tests; required_failure bloqueia; snapshot_overwrite false, TASK-008 — Gates determinísticos e snapshots, aif validate RUN-ID --profile NAME, ValidationGate.evaluate(context) -> GateResult

### Community 57 - "TASK-019/025 Context Builder & Benchmark"
Cohesion: 0.29
Nodes (7): Context Builder determinístico e seguro, TASK-025 Critérios de aceite, aif benchmark validate|run|report, BenchmarkManifest v1, BenchmarkRunner.run(manifest) -> BenchmarkResult, Harness de benchmark reproduzível, TASK-025 — Harness de benchmark reproduzível

### Community 58 - "TASK-024/026 Observability"
Cohesion: 0.29
Nodes (7): TASK-024 Critérios de aceite, aif telemetry check, correlation attributes, Observabilidade segura, TASK-024 — Observabilidade segura e release V0.4, Telemetry port, Isolamento de hidden tests

### Community 59 - "TASK-006 Process Runner Policy"
Cohesion: 0.29
Nodes (7): AC-001 — Metacaracteres permanecem argumento literal e executable/cwd fora da policy são rejeitados, AC-002 — Timeout/cancelamento encerra grupo inteiro sem órfãos, AC-003 — Segredo-canário, output excessivo e repo não confiável sem isolamento não vazam nem exaurem o host, ProcessRequest, ProcessResult, ProcessRunner.run(request) -> ProcessResult, TASK-006 — ProcessRunner seguro e limitado

### Community 60 - "SPEC Contract Documentation"
Cohesion: 0.33
Nodes (7): aif spec validate PATH [--task TASK-ID] [--json], Frontmatter fields (spec_id, schema_version, title), Limits (max_spec_bytes 1048576, max_tasks 200, max_dependency_depth 50), SPEC Contract v1, SpecParser, SpecValidator, Task sections (Depends on, Allowed paths, Acceptance criteria, Validation commands)

### Community 61 - "SPEC Schema Pattern Fields"
Cohesion: 0.29
Nodes (7): pattern, type, properties, minLength, type, ac_id, description

### Community 62 - "Portable Skills Tests"
Cohesion: 0.38
Nodes (4): _frontmatter_keys(), Path, test_both_hosts_reference_canonical_skills(), test_new_task_rejects_symlinked_planning_directory()

### Community 63 - "Engineering Standards & DoD"
Cohesion: 0.33
Nodes (6): Global Definition of Done, Mandatory Gate Command Set, F-06 — Supply-Chain Assurance Limited to Final SBOM, Normative Task Contract Template, GitHub Pull Request Template, README.md — Project Overview

### Community 64 - "TASK-020 Claude Code Adapter"
Cohesion: 0.33
Nodes (6): TASK-020 Critérios de aceite, Claude Code Adapter protegido, ClaudeCodeWorker.execute(request) -> AsyncIterator[AgentEvent], ClaudeNormalizer.feed(line: bytes) -> tuple[AgentEvent, ...], ClaudeRolePolicy, TASK-020 — Adapter Claude Code protegido

### Community 65 - "SPEC Schema Description Fields"
Cohesion: 0.33
Nodes (6): description, items, minItems, type, minLength, allowed_paths

### Community 66 - "Process Runner Contract Tests"
Cohesion: 0.60
Nodes (5): _fake_executable(), Path, Shared behavioral contract for ProcessRunner implementations., _request(), test_process_runner_contract_returns_sanitized_artifact_refs()

### Community 67 - "Cross-Task Closed Decisions"
Cohesion: 0.40
Nodes (5): max_concurrency 2; failure_policy continue-independent; provider_concurrency 1; merge proibido, release_authority humano; agente não tag/push; SBOM CycloneDX, shell=False, argv literal, allowlist vazia, fail-closed sem isolamento, hooks -c core.hooksPath=/dev/null; git_network proibida; cleanup_on_failure false, Validation rules (schema_version, DAG, path safety, argv-only commands)

### Community 68 - "SPEC Schema Tasks Array"
Cohesion: 0.40
Nodes (5): tasks, description, maxItems, minItems, type

### Community 69 - "Manual Validation Script"
Cohesion: 0.60
Nodes (4): find_task(), main(), Path, section()

### Community 70 - "Reviewer Portability Tests"
Cohesion: 0.50
Nodes (3): _frontmatter(), Path, test_reviewers_are_model_agnostic_and_read_only()

### Community 72 - "ADR-0003 Worktree Isolation Rationale"
Cohesion: 0.67
Nodes (4): ADR-0003 — Isolated Git Worktree per Task, GitWorktreeManager Adapter, WorkspaceManager Port, F-04 — Symlink/Traversal/Git-Hooks Not Explicit

### Community 73 - "SPEC Schema Task ID Field"
Cohesion: 0.50
Nodes (4): task_id, description, pattern, type

## Knowledge Gaps
- **241 isolated node(s):** `ai-software-factory`, `$schema`, `$id`, `title`, `description` (+236 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RunId` connect `Run/Task Persistence Correlation` to `Git Worktree Isolation`, `CLI Entry Point & Doctor`, `Filesystem Artifact Store`, `Process Runner Contract Tests`, `SQLite Connection & Migrations`, `Persistence Schema & Adapters`, `State Machine Transition Tests`, `Run Status Queries & Events`, `RunStore Port & State Machine`, `Asyncio Runner Artifact Persist`, `SQLiteRunStore Lifecycle Tests`, `Process Runner Tests`, `Process Request/Policy Models`, `Domain IDs & Task Execution`, `Task Execution Persistence Events`, `Process Result Models`, `Stream Capture & Redaction`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `SQLiteRunStore` connect `SQLiteRunStore Lifecycle Tests` to `CLI Entry Point & Doctor`, `SQLite Connection & Migrations`, `Persistence Schema & Adapters`, `Run/Task Persistence Correlation`, `Run Status Queries & Events`, `RunStore Port & State Machine`, `Domain IDs & Task Execution`, `Task Execution Persistence Events`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Why does `SoftwareSpec` connect `SpecValidator Checks` to `CLI Entry Point & Doctor`, `CLI Exit Code Tests`, `SpecParser Abuse Hardening`, `SpecValidator & Parser Tests`, `Spec Parser Task Builder`, `Spec Domain Models`, `Frontmatter Parsing`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `RunId` (e.g. with `FilesystemArtifactStore` and `SqliteEventLogReader`) actually correct?**
  _`RunId` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `DomainEvent` (e.g. with `FilesystemArtifactStore` and `SqliteEventLogReader`) actually correct?**
  _`DomainEvent` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `TaskId` (e.g. with `FilesystemArtifactStore` and `SqliteEventLogReader`) actually correct?**
  _`TaskId` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `SpecValidator` (e.g. with `SoftwareSpec` and `SpecValidationError`) actually correct?**
  _`SpecValidator` has 15 INFERRED edges - model-reasoned connections that need verification._