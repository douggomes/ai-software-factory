---
title: "TASK-021 — Planner cloud agnóstico com structured output"
task_id: TASK-021
release: "V0.3"
status: planned
depends_on: [TASK-019, TASK-020]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-021 — Planner cloud agnóstico com structured output

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md), [security-review.md](security-review.md) e [ADR-0005](../adr/0005-cloud-only-model-runtime.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Tasks recebem um plano estruturado de um coding agent cloud suportado, sem
autoridade para editar ou usar tools e sem acoplar o Core a um provider.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-019 e TASK-020 aprovadas.
- Baseline fixado no commit que integra ambas as dependências.
- Contract fixtures de OpenCode, Codex e Claude Code estão verdes offline.
- ADR-0005 aceito com inferência cloud-only e endpoints locais/self-hosted negados.

## Arquivos permitidos

- `src/ai_software_factory/ports/planning.py`
- `src/ai_software_factory/core/plan_models.py`
- `src/ai_software_factory/application/planner.py`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `schemas/plan-result.v1.schema.json`
- `prompts/planner.v1.md`
- `tests/contract/planning/**`
- `tests/integration/test_cloud_planner.py`
- `tests/security/test_cloud_planner_policy.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- adapters HTTP ou endpoints de inferência locais/self-hosted
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `Planner.plan(request: PlanRequest) -> PlanResult` | Schema v1; resultado é proposta não confiável sem edit/tool authority. |
| `CloudAgentPlanner` | Recebe `AgentWorker` por injeção e consome somente eventos normalizados; não conhece nome de provider. |
| `PlannerAuthority` | Read-only; zero filesystem write, subprocess/tool, Git, web ou external directory. |
| `aif doctor` planner probe | Reporta capabilities dos três CLIs sem chamada live, segredo, model output ou arquivo de autenticação. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `eligible_workers` | subset ordenado de `opencode`, `codex`, `claude-code` definido pelo profile |
| `inference_mode` | cloud-only; endpoint local/self-hosted é inválido |
| `authority` | read-only, tools=false, filesystem_write=false |
| `context_source` | somente ContextView mínima, classificada e aprovada pelo profile após SecretGate |
| `live_execution` | somente profile explícito; CI e gates usam fixtures/fake |
| `timeout_seconds` | 120 |
| `max_response_bytes` | 1_048_576 |
| `schema_additional_properties` | false |

## Passos de implementação

1. Fechar PlanResult/porta/prompt separados do contexto e da policy.
2. Implementar o planner sobre `AgentWorker` injetado, sem novo adapter de provider.
3. Validar schema, bytes e provenance; persistir worker/prompt/context/config hashes.
4. Testar fake/fixtures: success, unavailable, timeout, malformed, oversized, injection e endpoint proibido.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Planner elevar autoridade, vazar contexto ou abrir rota de inferência não aprovada | Worker injetado, context view mínima, papel read-only, allowlist cloud e schema sem campos de policy | `test_rejects_local_endpoint_and_authority_fields` |

## Critérios de aceite

- [ ] **AC-001** — FakeAgentWorker retorna PlanResult v1 válido com worker, prompt, contexto e config hashes.
- [ ] **AC-002** — Worker indisponível, timeout e output malformed/oversized falham tipados sem efeito externo ou provider oculto.
- [ ] **AC-003** — Endpoint local/self-hosted, segredo-canário e campos tentando alterar scope, gates, tools ou permissions são rejeitados antes da execução.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_cloud_planner.py::test_structured_plan_with_provenance -q` | schema v1, worker agnóstico e hashes aprovados | PlanResult artifact |
| AC-002 | `uv run pytest tests/integration/test_cloud_planner.py::test_failure_matrix_is_bounded -q` | failures normalizadas e zero chamada não declarada | failure matrix |
| AC-003 | `uv run pytest tests/security/test_cloud_planner_policy.py::test_rejects_local_endpoint_and_authority_fields -q` | processo não inicia, canário não sai e policy permanece imutável | process spy + security report |

## Validação manual no terminal

1. `uv run aif doctor --json`
   Esperado: OpenCode, Codex e Claude Code aparecem como elegíveis ou indisponíveis sem expor auth, fazer chamada live ou bloquear o Core.
2. `uv run pytest tests/integration/test_cloud_planner.py::test_structured_plan_with_provenance -q`
   Esperado: FakeAgentWorker produz PlanResult v1 com hashes/provenance e zero escrita.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-021` antes de publicar o draft PR.

## Fora de escopo

Chamada direta a provider API, inferência local/self-hosted, edição de código pelo planner, download de modelo e router LLM.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
