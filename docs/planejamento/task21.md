---
title: "TASK-021 — Planner Ollama local com structured output"
task_id: TASK-021
release: "V0.3"
status: planned
depends_on: [TASK-019, TASK-020]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-021 — Planner Ollama local com structured output

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Tasks recebem plano estruturado de modelo local sem custo incremental e sem autoridade para editar.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-019 e TASK-020 aprovadas.
- Baseline fixado no commit que integra ambas as dependências.
- Ollama real é opcional; servidor HTTP fake cobre a suite.

## Arquivos permitidos

- `src/ai_software_factory/ports/planning.py`
- `src/ai_software_factory/core/plan_models.py`
- `src/ai_software_factory/application/planner.py`
- `src/ai_software_factory/adapters/agents/ollama.py`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `schemas/plan-result.v1.schema.json`
- `prompts/planner.v1.md`
- `tests/contract/planning/**`
- `tests/integration/test_ollama_planner.py`
- `tests/security/test_ollama_endpoint.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `Planner.plan(request: PlanRequest) -> PlanResult` | Schema v1; resultado é proposta não confiável sem edit/tool authority. |
| `OllamaPlanner` | HTTP API com timeout, structured output e limites. |
| `aif doctor` planner probe | Somente `/api/version` e lista/modelo; ausência não bloqueia Core. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `endpoint` | `http://127.0.0.1:11434` somente loopback |
| `model` | `qwen3.5:9b` em exemplo configurável |
| `timeout_seconds` | 120 |
| `max_response_bytes` | 1_048_576 |
| `redirects` | false |
| `remote_endpoint` | deny; exige futura decisão TLS/auth |

## Passos de implementação

1. Fechar PlanResult/porta/prompt separados de contexto.
2. Implementar cliente HTTP limitado e loopback policy.
3. Validar schema, tokens/bytes e persistir hashes/version/digest.
4. Testar servidor fake: success, absent, timeout, redirect, malformed e injection.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Endpoint remoto/response hostil alterar policy | Loopback-only e schema sem autoridade | `test_rejects_remote_redirect_and_authority_fields` |

## Critérios de aceite

- [ ] **AC-001** — Servidor fake retorna PlanResult v1 válido com prompt/context/model hashes.
- [ ] **AC-002** — Ausência/timeout/malformed/oversized falham tipados sem bloquear outros workers ou conceder autoridade.
- [ ] **AC-003** — Endpoint não loopback, redirect e campos tentando alterar scope/gates/permissions são rejeitados.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_ollama_planner.py::test_structured_plan_with_provenance -q` | schema v1 e hashes aprovados | PlanResult artifact |
| AC-002 | `uv run pytest tests/integration/test_ollama_planner.py::test_failure_matrix_is_bounded -q` | failures normalizadas e pipeline disponível | failure matrix |
| AC-003 | `uv run pytest tests/security/test_ollama_endpoint.py::test_rejects_remote_redirect_and_authority_fields -q` | zero conexão remota e policy inalterada | network spy + security report |

## Validação manual no terminal

1. `uv run aif doctor --json`
   Esperado: Ollama e qwen3.5:9b aparecem disponíveis ou ausentes sem bloquear outros workers.
2. `uv run pytest tests/integration/test_ollama_planner.py::test_structured_plan_with_provenance -q`
   Esperado: O servidor fake produz PlanResult v1 com hashes/provenance.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-021` antes de publicar o draft PR.

## Fora de escopo

Download automático, endpoint remoto, edição de código pelo planner e router LLM.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
