---
title: "TASK-003 — Modelo de domínio e máquina de estados"
task_id: TASK-003
release: "V0.1"
status: planned
depends_on: [TASK-002]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-003 — Modelo de domínio e máquina de estados

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Runs, tasks e attempts possuem identidade e transições determinísticas independentes de banco, provider e CLI.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-002 aprovada e schema SPEC v1 presente.
- Baseline fixado no commit aprovado da TASK-002.
- Teste de arquitetura da TASK-001 ativo.

## Arquivos permitidos

- `src/ai_software_factory/core/ids.py`
- `src/ai_software_factory/core/models.py`
- `src/ai_software_factory/core/events.py`
- `src/ai_software_factory/core/state_machine.py`
- `src/ai_software_factory/core/failures.py`
- `tests/unit/core/**`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `transition(state: TaskStage, event: DomainEvent) -> Transition` | Função pura; transição inválida lança `InvalidTransition`. |
| `RunId`, `TaskId`, `AttemptId` | Value objects imutáveis, não intercambiáveis e serializáveis. |
| `TaskExecution` | Mantém run/task/base/worktree e budgets; sem ORM ou provider payload. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `initial_stage` | `Queued` |
| `terminal_stages` | `Succeeded`, `Rejected`, `Escalated`, `Cancelled` |
| `unknown_failure` | `HumanIntervention`; nunca retry automático |
| `event_schema_version` | `1` |

## Passos de implementação

1. Criar value objects e enums fechados.
2. Modelar entities/events sem dependência de infraestrutura.
3. Implementar tabela total de transições e invariantes.
4. Cobrir todas as arestas, estados terminais e falhas desconhecidas.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Estado impossível ou retry indevido | Máquina total e fail-closed | `test_all_transitions_and_terminal_invariants` |

## Critérios de aceite

- [ ] **AC-001** — Todas as transições documentadas possuem teste e resultado determinístico.
- [ ] **AC-002** — Estado terminal, evento desconhecido e identidade incompatível falham sem mutação.
- [ ] **AC-003** — Core não importa adapters, ORM, SDK ou nomes de provider.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/core/test_state_machine.py::test_all_transitions_and_terminal_invariants -q` | 100% da tabela de transição exercitada | coverage de branches do módulo |
| AC-002 | `uv run pytest tests/unit/core/test_state_machine.py::test_invalid_transition_is_atomic -q` | objeto original permanece igual | relatório pytest |
| AC-003 | `uv run lint-imports` | contratos de import aprovados | saída `lint-imports` |

## Fora de escopo

Persistência, CLI de status, scheduler, retry e adapters.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
