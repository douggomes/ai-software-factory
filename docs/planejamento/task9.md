---
title: "TASK-009 — Pipeline vertical offline com FakeAgentWorker"
task_id: TASK-009
release: "V0.1"
status: planned
depends_on: [TASK-008]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-009 — Pipeline vertical offline com FakeAgentWorker

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Uma task completa percorre SPEC, ledger, worktree, worker fake, diff, gates e resultado sem tokens.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-008 aprovada com gates operacionais.
- Baseline fixado no commit aprovado da TASK-008.
- Fixture Git e SPEC válida disponíveis.

## Arquivos permitidos

- `src/ai_software_factory/ports/workers.py`
- `src/ai_software_factory/core/agent_events.py`
- `src/ai_software_factory/adapters/agents/fake.py`
- `src/ai_software_factory/application/orchestrator.py`
- `src/ai_software_factory/cli.py`
- `schemas/run-report.v1.schema.json`
- `tests/contract/workers/**`
- `tests/integration/test_fake_pipeline.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `AgentWorker.execute(request: AgentExecutionRequest) -> AsyncIterator[AgentEvent]` | Eventos discriminados; sem payload de provider no Core. |
| `FactoryOrchestrator.run_task(command: RunTask) -> RunReport` | Coordena portas; não implementa Git/process/SQL. |
| `RunReport v1` | Identidade, outcome, diff/gate/artifact refs; JSON schema. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `fake_worker` | somente ambiente dev/test |
| `worker_authority` | write no worktree; sem commit/push/merge/rede |
| `unexpected_error` | attempt failed + evidência preservada |
| `policy_vs_context` | policy imutável separada de dados do repo |

## Passos de implementação

1. Definir worker port/event union e contract suite.
2. Implementar fake por roteiro com edits controlados.
3. Implementar orchestrator vertical por injeção de portas.
4. Criar E2E success, gate-fail, unexpected e prompt-injection fake.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Orchestrator confiar em output do worker | Eventos tipados e gates autoritativos | `test_repo_instruction_cannot_bypass_policy` |

## Critérios de aceite

- [ ] **AC-001** — Cenário offline success termina `Succeeded` somente após todos os gates.
- [ ] **AC-002** — Gate falho ou erro inesperado nunca produz sucesso e preserva worktree/evidência.
- [ ] **AC-003** — Instrução maliciosa no repo não amplia autoridade do fake/orchestrator.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_fake_pipeline.py::test_offline_success_end_to_end -q` | estado/eventos/relatório v1 aprovados | run report + event transcript |
| AC-002 | `uv run pytest tests/integration/test_fake_pipeline.py::test_failure_preserves_evidence -q` | outcome fail e worktree presente | ledger + diff hash |
| AC-003 | `uv run pytest tests/integration/test_fake_pipeline.py::test_repo_instruction_cannot_bypass_policy -q` | nenhuma ação proibida chamada | spy de capabilities |

## Validação manual no terminal

1. `uv run aif run examples/specs/ticket-feature.md --task TASK-001 --worker fake-success`
   Esperado: Executa o pipeline offline e termina Succeeded somente após os gates.
2. `uv run aif status <RUN-ID> --json`
   Esperado: Mostra attempts, diff, snapshots e artifacts do E2E fake.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-009` antes de publicar o draft PR.

## Fora de escopo

Provider real, retry, failover, reviewer, repair e scheduler.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
