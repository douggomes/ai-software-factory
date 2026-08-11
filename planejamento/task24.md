---
title: "TASK-024 — Observabilidade segura e release V0.4"
task_id: TASK-024
release: "V0.4"
status: planned
depends_on: [TASK-023]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-024 — Observabilidade segura e release V0.4

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Operadores correlacionam run/task/attempt/gates/MCP sem expor prompts, diffs ou segredos; V0.4 fica qualificada.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-023 aprovada com audit events MCP.
- Baseline fixado no commit aprovado da TASK-023.
- Exporters in-memory cobrem testes; OTLP real não é exigido.

## Arquivos permitidos

- `src/ai_software_factory/observability/tracing.py`
- `src/ai_software_factory/observability/metrics.py`
- `src/ai_software_factory/observability/logging.py`
- `src/ai_software_factory/application/**`
- `src/ai_software_factory/mcp/**`
- `src/ai_software_factory/cli.py`
- `tests/integration/test_observability.py`
- `tests/security/test_telemetry_redaction.py`
- `tests/release/test_v0_4.py`
- `docs/observability.md`
- `docs/releases/v0.4.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `Telemetry` port | Span/metric/log methods no-op capable; Core não importa OTel. |
| `aif telemetry check` | Emite sinal local de teste sem payload sensível. |
| `correlation attributes` | run/task/attempt/worker/provider/role/base/prompt/config hashes quando aplicável. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `telemetry.enabled` | true local |
| `exporter` | console; OTLP opt-in |
| `otlp_transport` | TLS obrigatório |
| `metric_ids` | run/task IDs proibidos como labels |
| `payloads` | prompt/diff/output proibidos como attributes |

## Passos de implementação

1. Definir adapter OTel atrás de porta/no-op.
2. Instrumentar services sem alterar domínio.
3. Implementar logs JSON e redaction antes de exporters.
4. Testar canários/cardinalidade/disable e produzir gate/dossier V0.4.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Telemetria exfiltrar segredo ou causar custo | Attribute allowlist, redaction e OTLP opt-in TLS | `test_canaries_never_reach_any_exporter` |

## Critérios de aceite

- [ ] **AC-001** — E2E failover+MCP produz árvore coerente e métricas sem IDs de alta cardinalidade.
- [ ] **AC-002** — Canários em prompt/output/exceção não chegam a log, trace, métrica ou exporter; endpoint inseguro falha.
- [ ] **AC-003** — Telemetry off não muda domínio e suite/dossier V0.4 são reproduzíveis offline.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_observability.py::test_correlated_failover_and_mcp_trace -q` | span tree/metrics golden | in-memory export snapshot |
| AC-002 | `uv run pytest tests/security/test_telemetry_redaction.py::test_canaries_never_reach_any_exporter -q` | secret scan zero e TLS policy | security report |
| AC-003 | `uv run pytest tests/release/test_v0_4.py -q` | no-op parity e release gate aprovados | dossier V0.4 + hashes |

## Fora de escopo

Dashboard próprio, alerting/retention remota e OpenTelemetry Logs experimental.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
