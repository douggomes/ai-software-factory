---
title: "TASK-010 — Taxonomia de falhas e seleção estática de workers"
task_id: TASK-010
release: "V0.1"
status: planned
depends_on: [TASK-009]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-010 — Taxonomia de falhas e seleção estática de workers

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

A Factory distingue falha operacional, qualidade e autoridade e explica elegibilidade/seleção sem depender de provider.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-009 aprovada com worker contract.
- Baseline fixado no commit aprovado da TASK-009.
- Fakes de eventos/falhas podem rodar offline.

## Arquivos permitidos

- `src/ai_software_factory/core/failures.py`
- `src/ai_software_factory/core/policies.py`
- `src/ai_software_factory/core/workers.py`
- `src/ai_software_factory/application/agent_pool.py`
- `src/ai_software_factory/cli.py`
- `tests/unit/test_failure_policy.py`
- `tests/unit/test_agent_pool.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `FailureNormalizer.normalize(error: ExternalFailure) -> NormalizedFailure` | Somente adapters criam ExternalFailure; Core usa categoria/disposição. |
| `AgentPoolSelector.select(request: SelectionRequest) -> RoutingDecision` | Ordem determinística; registra candidatos/exclusões/vencedor. |
| `aif workers explain --role ROLE` | Explicação JSON sem health dinâmica nesta task. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `quota_or_unavailable` | failover |
| `build_test_review` | repair; não degrada provider |
| `auth_permission_unknown` | human intervention |
| `selection_order` | ordem declarada em config |
| `no_candidate` | escalate com todas as razões |

## Passos de implementação

1. Fechar enums de categoria/disposição e tabela de política.
2. Modelar worker/capabilities/roles sem SDK.
3. Implementar filtro e ordem estática explicável.
4. Testar determinismo, unknown e ausência de string de provider no Core.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Falha desconhecida causar retry ou rota insegura | Unknown fail-closed para humano | `test_unknown_failure_never_retries` |

## Critérios de aceite

- [ ] **AC-001** — Tabela categoria→disposição é total, determinística e separa qualidade de saúde.
- [ ] **AC-002** — Worker inelegível/tentado/desabilitado nunca é selecionado e todas as razões são registradas.
- [ ] **AC-003** — Unknown escala para humano e Core não compara nomes/mensagens de provider.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/test_failure_policy.py::test_policy_table_is_total -q` | todas as enum values cobertas | snapshot da tabela |
| AC-002 | `uv run pytest tests/unit/test_agent_pool.py::test_filters_and_explains_every_candidate -q` | decisão golden estável | RoutingDecision JSON |
| AC-003 | `uv run pytest tests/unit/test_failure_policy.py::test_unknown_failure_never_retries -q && uv run lint-imports` | fail-closed e fronteiras aprovadas | pytest + lint-imports |

## Validação manual no terminal

1. `uv run aif workers explain --role implementer`
   Esperado: Lista candidatos, exclusões e selecionado em ordem determinística.
2. `uv run pytest tests/unit/test_failure_policy.py::test_unknown_failure_never_retries -q`
   Esperado: Confirma que falha unknown escala sem retry automático.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-010` antes de publicar o draft PR.

## Fora de escopo

Circuit breaker, score histórico, provider parsing e pacote de continuação.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
