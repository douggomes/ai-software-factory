---
title: "TASK-017 — Repair loop limitado e revalidação"
task_id: TASK-017
release: "V0.2"
status: planned
depends_on: [TASK-016]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-017 — Repair loop limitado e revalidação

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Falhas de gate/review recebem reparo direcionado com budget e revalidação completa, sem virar failover.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-016 aprovada com ReviewResult v1.
- Baseline fixado no commit aprovado da TASK-016.
- Worker fake repair e evaluator disponíveis offline.

## Arquivos permitidos

- `src/ai_software_factory/core/repair_models.py`
- `src/ai_software_factory/application/repair.py`
- `src/ai_software_factory/application/orchestrator.py`
- `schemas/repair-result.v1.schema.json`
- `prompts/repair.v1.md`
- `tests/integration/test_repair_loop.py`
- `tests/chaos/test_repair_restart.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `RepairService.repair(request: RepairRequest) -> RepairOutcome` | Nova attempt kind=repair; contexto somente issues/ACs/gates/diff atuais. |
| `RepairBudget` | Persistido por task; atômico e separado de retry/failover. |
| `RepairOutcome` | Sempre seguido por gates; semantic failure também re-review. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `max_repair_attempts` | 2 |
| `repair_context` | sem transcripts históricos/artifacts irrelevantes |
| `gate_after_repair` | sempre |
| `review_after_semantic_repair` | sempre |
| `budget_exhausted` | Escalated |

## Passos de implementação

1. Fechar modelos/schema e prompt repair.
2. Implementar budget persistido e attempts tipadas.
3. Integrar gate→repair→gate e review→repair→gate→review.
4. Testar restart, exaustão, prompt injection e separação de contadores.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Loop infinito ou reparo ampliar scope | Budget persistido e mesmos gates/scope | `test_budget_scope_and_restart_are_enforced` |

## Critérios de aceite

- [ ] **AC-001** — Gate fail pode ser reparado e só termina success após gates novos.
- [ ] **AC-002** — Review fail exige repair, gates e novo review; repair nunca conta como failover.
- [ ] **AC-003** — Budget persiste em restart, limita duas attempts e exaustão escala preservando evidência.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_repair_loop.py::test_gate_failure_repair_and_revalidate -q` | snapshot novo obrigatório | attempt graph + validations |
| AC-002 | `uv run pytest tests/integration/test_repair_loop.py::test_semantic_repair_requires_rereview -q` | contadores e sequência exatos | event transcript |
| AC-003 | `uv run pytest tests/chaos/test_repair_restart.py -q` | sem attempt extra após restart | ledger/budget snapshot |

## Fora de escopo

Aprovação humana, commit, failover usado como repair e loop sem limite.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
