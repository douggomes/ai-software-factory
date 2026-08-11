---
title: "TASK-012 — Continuation Package e failover retomável"
task_id: TASK-012
release: "V0.1"
status: planned
depends_on: [TASK-011]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-012 — Continuation Package e failover retomável

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Trabalho parcial sobrevive a quota/indisponibilidade e continua em outro worker no mesmo worktree.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-011 aprovada com seleção e circuit breaker.
- Baseline fixado no commit aprovado da TASK-011.
- Cenário Fake #1/Fake #2 da TASK-009 disponível.

## Arquivos permitidos

- `src/ai_software_factory/application/continuation.py`
- `src/ai_software_factory/core/continuation_models.py`
- `src/ai_software_factory/application/orchestrator.py`
- `schemas/continuation-package.v1.schema.json`
- `tests/integration/test_continuation.py`
- `tests/chaos/test_continuation_boundary.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ContinuationPackageBuilder.build(attempt: AttemptSnapshot) -> ContinuationPackage` | Schema v1 imutável; refs/hash, nunca transcript bruto. |
| `ContinuationPackage.verify(context: RunContext) -> VerifiedContinuation` | Revalida run/task/base/worktree/artifact hashes. |
| `ExecutionAttempt.parent_attempt_id` | Segunda attempt referencia primeira; mesma TaskExecution. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `retry_budget` | 1 |
| `failover_budget` | 2 |
| `repair_budget` | separado; não consumido aqui |
| `package_overwrite` | false |
| `continuation_worker` | exclui workers já tentados e circuito aberto |

## Passos de implementação

1. Fechar schema/package refs e budgets.
2. Criar package atomicamente antes da seleção seguinte.
3. Integrar failover no orchestrator preservando worktree/identidade.
4. Adicionar E2E fake e kill point package-created/attempt-not-started.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Pacote adulterado ou cross-run assumir autoridade | Hash, canonical paths e identidade completa | `test_rejects_tampered_cross_run_package` |

## Critérios de aceite

- [ ] **AC-001** — Quota do Fake #1 produz package v1 e Fake #2 continua no mesmo worktree com diff parcial.
- [ ] **AC-002** — Package adulterado, oversized, externo, cross-run ou com segredo é rejeitado antes do worker.
- [ ] **AC-003** — Reinício após package criado não duplica package/attempt e budgets permanecem separados.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_continuation.py::test_failover_preserves_partial_work -q` | duas attempts e diff combinado | package + grafo attempts |
| AC-002 | `uv run pytest tests/integration/test_continuation.py::test_rejects_tampered_cross_run_package -q` | zero invocações de worker | security result snapshot |
| AC-003 | `uv run pytest tests/chaos/test_continuation_boundary.py -q` | IDs e contadores não duplicados | ledger antes/depois restart |

## Fora de escopo

Provider real, compactação por LLM, review e repair.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
