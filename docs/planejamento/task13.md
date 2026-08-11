---
title: "TASK-013 — Adapter OpenCode protegido"
task_id: TASK-013
release: "V0.1"
status: planned
depends_on: [TASK-012]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-013 — Adapter OpenCode protegido

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

A Factory usa seu primeiro coding agent real mantendo contratos, deny-by-default e controle de custo.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-012 aprovada com failover offline.
- Baseline fixado no commit aprovado da TASK-012.
- OpenCode disponível somente para smoke opt-in; contract fixtures cobrem CI.

## Arquivos permitidos

- `src/ai_software_factory/adapters/agents/opencode.py`
- `src/ai_software_factory/adapters/agents/opencode_normalizer.py`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `examples/opencode.factory.json`
- `tests/contract/agents/opencode/**`
- `tests/security/test_opencode_policy.py`
- `docs/providers/opencode.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `OpenCodeWorker.execute(request) -> AsyncIterator[AgentEvent]` | Invoca `opencode run --format json --dir WORKTREE` via ProcessRunner. |
| `OpenCodeNormalizer.feed(line: bytes) -> tuple[AgentEvent, ...]` | JSON limitado; erro/evento desconhecido explícito. |
| `aif agent smoke opencode` | Opt-in; preflight e confirmação; nunca parte da suite padrão. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `permissions` | deny external_directory, web, `.env`, commit, push e merge |
| `auto_mode` | false; só true em perfil com denies testados |
| `max_event_bytes` | 1_048_576 |
| `billing_guard` | bloqueia API key incremental quando `no_incremental_cost=true` |
| `model_id` | config obrigatório e validado; nunca no Core |

## Passos de implementação

1. Implementar normalizador incremental a partir de fixtures.
2. Implementar worker via ProcessRunner e capability discovery.
3. Criar perfil deny-by-default e Billing Guard.
4. Adicionar contract/security tests offline e smoke explicitamente marcado.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Project instruction/prompt injection elevar permissão | Policy externa, capabilities mínimas e gates autoritativos | `test_repo_prompt_cannot_enable_denied_capabilities` |

## Critérios de aceite

- [ ] **AC-001** — Fixtures success/quota/rate-limit/partial/malformed normalizam para eventos de domínio corretos.
- [ ] **AC-002** — Repo malicioso não libera web, external dir, Git ou segredo e output excessivo é limitado.
- [ ] **AC-003** — Preflight bloqueia model inexistente/API key proibida; testes padrão nunca chamam OpenCode.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/contract/agents/opencode -q` | contract suite compartilhada aprovada | fixture/result matrix |
| AC-002 | `uv run pytest tests/security/test_opencode_policy.py::test_repo_prompt_cannot_enable_denied_capabilities -q` | spies proibidos zerados | policy audit snapshot |
| AC-003 | `uv run pytest tests/security/test_opencode_policy.py::test_preflight_and_offline_suite -q` | falha antes do processo; zero live calls | preflight report |

## Validação manual no terminal

1. `uv run pytest tests/contract/agents/opencode -q`
   Esperado: Fixtures OpenCode passam sem chamada real ao provider.
2. `uv run aif agent smoke opencode`
   Esperado: Somente quando desejado, executa preflight/smoke controlado respeitando Billing Guard.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-013` antes de publicar o draft PR.

## Fora de escopo

Servidor persistente, attach, Codex, review e escolha por score.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
