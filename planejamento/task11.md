---
title: "TASK-011 — Circuit Breaker e saúde de providers"
task_id: TASK-011
release: "V0.1"
status: planned
depends_on: [TASK-010]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-011 — Circuit Breaker e saúde de providers

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Falhas operacionais abrem circuitos por provider de forma previsível, sem confundir qualidade do código com indisponibilidade.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-010 aprovada com taxonomia total.
- Baseline fixado no commit aprovado da TASK-010.
- Relógio e store de health podem ser injetados em testes.

## Arquivos permitidos

- `src/ai_software_factory/core/provider_health.py`
- `src/ai_software_factory/ports/provider_health.py`
- `src/ai_software_factory/adapters/persistence/sqlite.py`
- `src/ai_software_factory/application/agent_pool.py`
- `src/ai_software_factory/cli.py`
- `migrations/**`
- `tests/unit/test_circuit_breaker.py`
- `tests/integration/test_provider_health_store.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `CircuitBreaker.record(worker: WorkerRef, failure: NormalizedFailure, now: Instant) -> CircuitDecision` | Somente falha operacional elegível altera health. |
| `ProviderHealthStore` | Persistência versionada por worker/provider/capability. |
| `aif workers health` | Snapshot read-only com Closed/Open/HalfOpen e expiry. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `quota_open_seconds` | 3600 |
| `unavailable_open_seconds` | 300 |
| `rate_limit_retry_seconds` | 30; respeitar retry-after menor/igual a 300 |
| `half_open_probes` | 1 |
| `quality_failure_health_effect` | nenhum |

## Passos de implementação

1. Modelar estados e decisões puras com relógio injetado.
2. Persistir health e migration sem compartilhar sessão.
3. Integrar seleção estática com circuit state.
4. Testar concorrência HalfOpen, eventos atrasados e cross-run.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Evento forjado envenenar saúde | Vincular attempt/worker e normalizar antes de registrar | `test_rejects_stale_or_cross_attempt_event` |

## Critérios de aceite

- [ ] **AC-001** — Quota/unavailable abrem circuito pela janela normativa; quality failure não altera health.
- [ ] **AC-002** — HalfOpen permite uma única sonda concorrente e fecha/reabre conforme resultado.
- [ ] **AC-003** — Evento atrasado, forjado ou de attempt diferente não altera o snapshot.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/test_circuit_breaker.py::test_operational_vs_quality_failures -q` | tabela de estados exata | snapshot de CircuitDecision |
| AC-002 | `uv run pytest tests/integration/test_provider_health_store.py::test_single_half_open_probe -q` | uma probe obtida entre concorrentes | eventos de lease |
| AC-003 | `uv run pytest tests/unit/test_circuit_breaker.py::test_rejects_stale_or_cross_attempt_event -q` | health permanece idêntica | before/after snapshot |

## Fora de escopo

Score histórico, chamadas reais a provider e failover com continuação.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
