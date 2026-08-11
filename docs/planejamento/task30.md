---
title: "TASK-030 — Scheduler DAG com paralelismo isolado"
task_id: TASK-030
release: "V1.1"
status: planned
depends_on: [TASK-029]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-030 — Scheduler DAG com paralelismo isolado

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Tasks independentes executam em paralelo com isolamento/bulkheads; dependentes aguardam aprovação e falhas não atravessam ramos.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-029 aprovada com routing decision.
- Baseline fixado no commit aprovado da TASK-029.
- SPEC DAG e pipelines seriais são estáveis.

## Arquivos permitidos

- `src/ai_software_factory/core/scheduler_models.py`
- `src/ai_software_factory/application/scheduler.py`
- `src/ai_software_factory/application/orchestrator.py`
- `src/ai_software_factory/cli.py`
- `tests/integration/test_dag_scheduler.py`
- `tests/chaos/test_parallel_isolation.py`
- `tests/security/test_cross_task_isolation.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `TaskScheduler.run(dag, policy) -> RunAggregate` | `asyncio.TaskGroup`; uma pipeline/worktree/session por task. |
| `SchedulerPolicy` | max concurrency, provider limits, fail-fast ou continue-independent. |
| `aif run SPEC --all --max-concurrency N` | N validado; serial N=1 é baseline. |
| `RunAggregate` | Outcomes individuais completos; não auto-merge. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `max_concurrency` | 2 no perfil local inicial |
| `failure_policy` | continue-independent |
| `provider_concurrency` | 1 por provider salvo config menor/igual global |
| `dependent_start` | somente prerequisite aprovado |
| `merge` | proibido |

## Passos de implementação

1. Modelar DAG runtime/aggregate e policy.
2. Implementar scheduler com TaskGroup, semaphore e bulkheads.
3. Isolar worktree/DB session/MCP/env/HOME/TMP/artifacts por task.
4. Criar timeline E2E, failure/cancel/saturation/cross-task tests.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Cross-task leak ou cascading failure | Isolamento por identidade e bulkheads | `test_tasks_never_share_context_state_or_credentials` |

## Critérios de aceite

- [ ] **AC-001** — Duas tasks independentes sobrepõem tempo; dependente inicia somente após aprovação.
- [ ] **AC-002** — Uma task nunca tem dois writers e recursos/contexto/MCP/env/artifacts não cruzam tasks.
- [ ] **AC-003** — Falha/cancel/saturation segue policy e preserva outcomes; N=1 reproduz baseline serial.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_dag_scheduler.py::test_parallel_independent_then_dependent -q` | timeline comprova overlap/order | scheduler timeline |
| AC-002 | `uv run pytest tests/security/test_cross_task_isolation.py::test_tasks_never_share_context_state_or_credentials -q` | canários isolados e locks únicos | isolation report |
| AC-003 | `uv run pytest tests/chaos/test_parallel_isolation.py -q` | policies/bulkheads/backpressure corretos | chaos aggregate snapshots |

## Validação manual no terminal

1. `uv run aif run <SPEC-DAG> --all --max-concurrency 2 --worker fake-success`
   Esperado: Tasks independentes sobrepõem; dependente aguarda aprovação.
2. `uv run pytest tests/security/test_cross_task_isolation.py -q`
   Esperado: Contexto, MCP, env, artifacts e credenciais não cruzam tasks.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-030` antes de publicar o draft PR.

## Fora de escopo

Merge paralelo, conflict resolution, execução distribuída, autoscaling e fila remota.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
