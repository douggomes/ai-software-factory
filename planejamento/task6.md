---
title: "TASK-006 — ProcessRunner seguro e limitado"
task_id: TASK-006
release: "V0.1"
status: planned
depends_on: [TASK-005]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-006 — ProcessRunner seguro e limitado

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

A Factory executa processos sem shell, com ambiente mínimo, limites e cancelamento confiável.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-005 aprovada e ArtifactStore disponível.
- Baseline fixado no commit aprovado da TASK-005.
- Testes rodam somente com executáveis fake em diretório temporário.

## Arquivos permitidos

- `src/ai_software_factory/ports/processes.py`
- `src/ai_software_factory/adapters/process/asyncio_runner.py`
- `src/ai_software_factory/core/process_models.py`
- `tests/contract/processes/**`
- `tests/integration/process_fixtures/**`
- `tests/integration/test_process_runner.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ProcessRunner.run(request: ProcessRequest) -> ProcessResult` | `argv: tuple[str, ...]`; streaming sanitizado; `shell=False`. |
| `ProcessRequest` | Executable/cwd/env policy, timeout, byte/resource limits e trust profile. |
| `ProcessResult` | Exit/signal/duração/truncated/stdout_ref/stderr_ref; nunca segredo bruto. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `timeout_seconds` | 900 |
| `termination_grace_seconds` | 5 |
| `max_output_bytes` | 4_194_304 por stream |
| `environment` | allowlist vazia + PATH mínimo controlado |
| `untrusted_without_isolation` | fail-closed |

## Passos de implementação

1. Definir request/result e porta estreita.
2. Implementar subprocess group, streaming limitado e redaction antes de artifact.
3. Implementar timeout/cancelamento TERM→KILL e HOME/TMP efêmeros.
4. Criar fakes para injection, órfão, flood, segredo e isolamento ausente.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Command injection ou escape do host | Sem shell, policy e isolamento forte para não confiável | `test_literal_args_timeout_children_and_canary` |

## Critérios de aceite

- [ ] **AC-001** — Metacaracteres permanecem argumento literal e executable/cwd fora da policy são rejeitados.
- [ ] **AC-002** — Timeout/cancelamento encerra grupo inteiro sem órfãos.
- [ ] **AC-003** — Segredo-canário, output excessivo e repo não confiável sem isolamento não vazam nem exaurem o host.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_process_runner.py::test_arguments_are_literal_and_policy_enforced -q` | fake recebe argv exato | captura argv sanitizada |
| AC-002 | `uv run pytest tests/integration/test_process_runner.py::test_timeout_kills_process_group -q` | PID pai/filho inexistentes ao retornar | relatório de PIDs |
| AC-003 | `uv run pytest tests/integration/test_process_runner.py::test_canary_limits_and_fail_closed -q` | canário ausente; truncation e fail-closed observados | artifacts sanitizados |

## Fora de escopo

Backend concreto de container/VM, gates de qualidade e comandos remotos.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
