---
title: "TASK-029 — Roteamento dinâmico explicável"
task_id: TASK-029
release: "V1.1"
status: planned
depends_on: [TASK-028]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-029 — Roteamento dinâmico explicável

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Workers são escolhidos por features, capacidades, saúde e histórico íntegro com replay e fallback estático.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- V1.0 aprovada na TASK-028.
- Baseline fixado no commit aprovado da TASK-028.
- BenchmarkResult v1 fornece dataset com provenance e segmentação.

## Arquivos permitidos

- `src/ai_software_factory/application/routing/features.py`
- `src/ai_software_factory/application/routing/scoring.py`
- `src/ai_software_factory/application/routing/decision.py`
- `src/ai_software_factory/application/agent_pool.py`
- `src/ai_software_factory/cli.py`
- `schemas/routing-decision.v1.json`
- `tests/unit/routing/**`
- `tests/security/test_router_poisoning.py`
- `docs/adr/0006-explainable-routing-over-llm-router.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `FeatureExtractor.extract(task, context) -> RoutingFeatures` | Determinístico; category/risk validados, não aceitos do modelo. |
| `ScoringPolicy.score(candidate, features, history) -> ScoreBreakdown` | Pesos/config versionados; security eligibility precede score. |
| `RoutingDecision v1` | Inputs/dataset hash/weights/candidates/exclusions/scores/winner/fallback. |
| `aif route explain` | Read-only/replay; sem provider call. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `min_samples` | 5 por segmento |
| `insufficient_data` | ordem estática V1.0 |
| `tie_break` | ordem estável configurada |
| `dynamic_router.enabled` | false até habilitação explícita |
| `open_circuit_or_ineligible` | sempre excluído |

## Passos de implementação

1. Definir features/decision schema e provenance.
2. Implementar scoring puro, segmentação e fallback.
3. Integrar sob feature flag preservando selector V1.0.
4. Criar property/replay/poisoning/outlier/rollback tests.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Histórico envenenado reduzir segurança | Integrity/provenance, baseline e eligibility absoluta | `test_poisoned_history_cannot_change_eligibility` |

## Critérios de aceite

- [ ] **AC-001** — Mesmos inputs/history hash produzem decisão byte a byte idêntica e explicada.
- [ ] **AC-002** — Poucas amostras, outlier ou dataset inválido acionam/rejeitam para baseline sem custo.
- [ ] **AC-003** — Poisoning nunca torna worker inelegível elegível nem altera permissions/budgets; flag off restaura V1.0.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/routing/test_determinism.py -q` | golden decision/replay igual | RoutingDecision v1 |
| AC-002 | `uv run pytest tests/unit/routing/test_fallback.py -q` | fallback reasons e zero provider calls | replay report |
| AC-003 | `uv run pytest tests/security/test_router_poisoning.py::test_poisoned_history_cannot_change_eligibility -q` | policy invariants intactos | security decision diff |

## Fora de escopo

LLM router, bandits, online learning, auto tuning de prompts e mudança silenciosa de budgets.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
