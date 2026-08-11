---
title: "TASK-018 — Human gate, commit seguro e release V0.2"
task_id: TASK-018
release: "V0.2"
status: planned
depends_on: [TASK-017]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-018 — Human gate, commit seguro e release V0.2

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Um humano aprova/rejeita exatamente a base e o diff validados; somente a Factory pode criar commit sem hooks.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-017 aprovada com repair/re-review.
- Baseline fixado no commit aprovado da TASK-017.
- Gates e review atuais vinculáveis a hashes.

## Arquivos permitidos

- `src/ai_software_factory/core/approval_models.py`
- `src/ai_software_factory/application/approval.py`
- `src/ai_software_factory/application/orchestrator.py`
- `src/ai_software_factory/cli.py`
- `migrations/**`
- `tests/integration/test_human_gate.py`
- `tests/security/test_approval_toctou.py`
- `docs/releases/v0.2.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `aif approve RUN-ID --actor ACTOR` | Cria Approval para base+worktree+diff+gate+review hashes atuais. |
| `aif reject RUN-ID --actor ACTOR --reason TEXT` | Terminal; preserva worktree/evidência. |
| `CommitService.commit(approval: Approval) -> CommitResult` | Revalida tudo, repete gates e usa hooks desabilitados. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `approval_required` | true |
| `commit_enabled` | true após approval |
| `push_merge` | proibidos |
| `hooks` | desabilitados |
| `any_worktree_change` | invalida approval |

## Passos de implementação

1. Criar model/tabela/eventos de approval.
2. Implementar approve/reject e identidade composta.
3. Implementar revalidação imediata e commit seguro pela Factory.
4. Criar TOCTOU/security tests e dossier V0.2.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Mudança entre approve e commit | Hash completo e revalidação imediata fail-closed | `test_any_change_invalidates_approval` |

## Critérios de aceite

- [ ] **AC-001** — Approve só ocorre com gates/review atuais e persiste identidade/hash/ator/timestamp.
- [ ] **AC-002** — Qualquer byte, untracked, symlink, base ou snapshot alterado invalida e bloqueia commit.
- [ ] **AC-003** — Commit contém metadata do run, não executa hooks; reject preserva evidência e push/merge nunca são chamados.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_human_gate.py::test_approval_binds_exact_evidence -q` | Approval identity completa | approval row + event |
| AC-002 | `uv run pytest tests/security/test_approval_toctou.py::test_any_change_invalidates_approval -q` | todos os TOCTOU cases bloqueados | security matrix |
| AC-003 | `uv run pytest tests/integration/test_human_gate.py::test_commit_without_hooks_and_reject_preserves -q` | commit local exato; spies push/merge zerados | commit/show + ledger |

## Validação manual no terminal

1. `uv run aif approve <RUN-ID> --actor <USUARIO>`
   Esperado: Aprovação do produto vincula base, worktree, diff, gates e review exatos.
2. `uv run aif reject <OUTRO-RUN-ID> --actor <USUARIO> --reason teste-manual`
   Esperado: Reject encerra o run preservando worktree/evidência e sem push/merge.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-018` antes de publicar o draft PR.

## Fora de escopo

Merge/push automático, aprovação remota, UI e assinatura criptográfica de release.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
