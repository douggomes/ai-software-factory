---
title: "TASK-007 — Worktree Git isolado e cleanup seguro"
task_id: TASK-007
release: "V0.1"
status: planned
depends_on: [TASK-006]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-007 — Worktree Git isolado e cleanup seguro

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Cada task recebe workspace Git isolado, idempotente e inspecionável sem alterar o checkout principal.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-006 aprovada com ProcessRunner.
- Baseline fixado no commit aprovado da TASK-006.
- Fixture cria repositório Git temporário sem hooks confiáveis.

## Arquivos permitidos

- `src/ai_software_factory/ports/workspace.py`
- `src/ai_software_factory/core/workspace_models.py`
- `src/ai_software_factory/adapters/git/worktrees.py`
- `src/ai_software_factory/cli.py`
- `tests/contract/workspace/**`
- `tests/integration/test_git_worktree.py`
- `docs/adr/0003-git-worktree-per-task.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `WorkspaceManager.prepare(request: WorkspaceRequest) -> Workspace` | Valida repo/base/run/task; cria branch/worktree e lock único. |
| `WorkspaceManager.inspect(workspace: Workspace) -> WorkspaceSnapshot` | Status, diff, changed files e stats sem hooks. |
| `WorkspaceManager.clean(workspace: Workspace) -> None` | Somente identidade persistida sob factory home; confirmação externa. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `hooks` | `-c core.hooksPath=/dev/null` em todo Git controlado |
| `worktree_root` | `<factory_home>/worktrees/<repo>/<run>/<task>` |
| `writers_per_task` | 1 |
| `cleanup_on_failure` | false |
| `git_network` | proibida |

## Passos de implementação

1. Definir identidades/workspace port.
2. Implementar comandos Git por argv, `--` e hooks desabilitados.
3. Implementar lock, reentrada idempotente, inspect e scope-safe cleanup.
4. Testar traversal, symlink swap, hook malicioso e dois writers.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Cleanup/Hook comprometer host | Identidade+canonical path e hooks desabilitados | `test_rejects_escape_and_never_runs_hooks` |

## Critérios de aceite

- [ ] **AC-001** — Prepare idempotente cria worktree na base exata e não altera checkout principal.
- [ ] **AC-002** — Dois writers não obtêm o mesmo lock e workspace incompatível falha.
- [ ] **AC-003** — Traversal, symlink/TOCTOU, path externo e hook malicioso não executam nem são removidos.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_git_worktree.py::test_prepare_is_idempotent_and_isolated -q` | HEAD/base/path exatos; checkout limpo | snapshot Git |
| AC-002 | `uv run pytest tests/integration/test_git_worktree.py::test_single_writer_lock -q` | uma aquisição e uma rejeição | eventos de lock |
| AC-003 | `uv run pytest tests/integration/test_git_worktree.py::test_rejects_escape_and_never_runs_hooks -q` | canário hook ausente e alvo externo intacto | relatório abuse tests |

## Validação manual no terminal

1. `uv run aif run examples/specs/ticket-feature.md --task TASK-001 --dry-run`
   Esperado: Cria/inspeciona worktree isolado sem modificar o checkout principal.
2. `uv run aif workspace inspect <RUN-ID>`
   Esperado: Exibe base commit, branch, path, lock e diff do workspace correto.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-007` antes de publicar o draft PR.

## Fora de escopo

Commit, push, merge, conflict resolution e worktrees paralelos.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
