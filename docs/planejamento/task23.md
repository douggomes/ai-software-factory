---
title: "TASK-023 — Servidor MCP semântico e isolado"
task_id: TASK-023
release: "V0.4"
status: planned
depends_on: [TASK-022]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-023 — Servidor MCP semântico e isolado

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Workers consultam task, diff e validação por tools tipadas e mínimas, sem shell genérico ou acesso cross-run.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- V0.3 aprovada na TASK-022.
- Baseline fixado no commit aprovado da TASK-022.
- SDK MCP Python fixado no lock após revisão de dependência.

## Arquivos permitidos

- `src/ai_software_factory/mcp/models.py`
- `src/ai_software_factory/mcp/tools.py`
- `src/ai_software_factory/mcp/server.py`
- `src/ai_software_factory/config.py`
- `examples/mcp/**`
- `tests/contract/mcp/**`
- `tests/integration/test_mcp_stdio.py`
- `tests/security/test_mcp_isolation.py`
- `docs/adr/0005-semantic-mcp-no-generic-shell.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `factory_get_task` | Sem args de ID externo; usa sessão autorizada; payload v1 limitado. |
| `factory_get_solution_map` / `factory_get_git_diff` | Read-only e somente worktree da sessão. |
| `factory_run_validation(profile: RegisteredProfile)` | Mesmo Evaluator autoritativo; sem argv livre. |
| `factory_get_validation_result(snapshot_id)` | Somente snapshot da task/sessão atual. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `transport` | stdio local |
| `write_tools` | nenhuma |
| `dynamic_tool_registration` | false |
| `rate_limit` | 60 calls/min por sessão |
| `timeout_seconds` | 30 |
| `mcp.enabled` | false até configurado por worker |

## Passos de implementação

1. Definir I/O schemas e autorização por sessão/chamada.
2. Implementar tools sobre services existentes, sem duplicar regras.
3. Implementar FastMCP stdio, budgets, rate/time limits e audit events.
4. Testar contract, replay, cross-run, prompt injection e parity CLI.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Confused deputy ou tool replay cross-run | Reautorização completa em cada chamada | `test_rejects_cross_run_replay_and_session_swap` |

## Critérios de aceite

- [ ] **AC-001** — Cinco tools retornam schemas v1 e validation usa o mesmo evaluator da CLI.
- [ ] **AC-002** — ID forjado, replay, sessão cross-run, worktree swap e oversized input/output são rejeitados.
- [ ] **AC-003** — Não existe tool equivalente a command/write; prompt injection em tool result não dispara ação.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/contract/mcp tests/integration/test_mcp_stdio.py::test_cli_evaluator_parity -q` | contract + parity aprovados | stdio transcript sanitizado |
| AC-002 | `uv run pytest tests/security/test_mcp_isolation.py::test_rejects_cross_run_replay_and_session_swap -q` | todas as chamadas hostis negadas | audit events |
| AC-003 | `uv run pytest tests/security/test_mcp_isolation.py::test_no_generic_or_chained_authority -q` | tool registry fechado e zero ação encadeada | registered-tools snapshot |

## Validação manual no terminal

1. `uv run pytest tests/integration/test_mcp_stdio.py::test_cli_evaluator_parity -q`
   Esperado: MCP stdio usa o mesmo evaluator da CLI.
2. `uv run pytest tests/security/test_mcp_isolation.py::test_rejects_cross_run_replay_and_session_swap -q`
   Esperado: Sessão não acessa outro run/task nem aceita replay.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-023` antes de publicar o draft PR.

## Fora de escopo

HTTP/OAuth, servidor remoto, tools de escrita e registro dinâmico.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
