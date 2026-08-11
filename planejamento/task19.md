---
title: "TASK-019 — Context Builder determinístico e seguro"
task_id: TASK-019
release: "V0.3"
status: planned
depends_on: [TASK-018]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-019 — Context Builder determinístico e seguro

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Cada papel recebe contexto mínimo, reproduzível, com origem/hash e sem elevar instruções do repositório a policy.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- V0.2 aprovada na TASK-018.
- Baseline fixado no commit aprovado da TASK-018.
- Allowed scope e workspace snapshot disponíveis.

## Arquivos permitidos

- `src/ai_software_factory/context/models.py`
- `src/ai_software_factory/context/policies.py`
- `src/ai_software_factory/context/builder.py`
- `src/ai_software_factory/application/prompt_builder.py`
- `src/ai_software_factory/cli.py`
- `schemas/context-manifest.v1.schema.json`
- `tests/unit/context/**`
- `tests/security/test_context_boundaries.py`
- `docs/adr/0004-deterministic-context-before-embeddings.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ContextBuilder.build(request: ContextRequest) -> ContextManifest` | Seleção pura/ordenada por scope, referências, imports e testes. |
| `ContextManifest v1` | Path relativo, reason, size, SHA-256, order e omitted reason. |
| `PromptBuilder.build(view: ContextView) -> PromptArtifact` | Policy e dados não confiáveis separados; budget aplicado. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `max_files` | 200 |
| `max_total_bytes` | 2_097_152 |
| `max_file_bytes` | 262_144 |
| `sensitive_files` | deny |
| `special_files_and_symlinks` | deny |
| `role_views` | planner,implementer,reviewer explícitas |

## Passos de implementação

1. Fechar models/schema e seleção estável.
2. Implementar discovery/canonicalização sem arquivos especiais/symlink.
3. Implementar budgets/omissions e views por role.
4. Adicionar golden, TOCTOU, canary e prompt-injection tests.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Context poisoning ou leitura externa | Provenance, rotulagem e canonicalização no uso | `test_rejects_symlink_special_file_and_injection` |

## Critérios de aceite

- [ ] **AC-001** — Mesma base/task/config produz manifest byte a byte idêntico; mudança de arquivo altera hashes.
- [ ] **AC-002** — Budget registra omissões; segredo, path externo, symlink, special file e TOCTOU são rejeitados.
- [ ] **AC-003** — Instrução no repo permanece dado e não altera policy/capabilities; reviewer não recebe transcript do implementer.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/context/test_builder.py::test_manifest_is_byte_stable -q` | golden/hash estáveis | context-manifest fixture |
| AC-002 | `uv run pytest tests/security/test_context_boundaries.py::test_rejects_symlink_special_file_and_injection -q` | todos os abuse cases fail-closed | security report |
| AC-003 | `uv run pytest tests/unit/context/test_role_views.py -q` | views mínimas e policy separada | prompt/context hashes |

## Fora de escopo

Embeddings, vector DB, reranker LLM e tools MCP.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
