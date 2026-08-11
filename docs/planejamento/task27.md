---
title: "TASK-027 — Recovery e idempotência por estágio"
task_id: TASK-027
release: "V1.0"
status: planned
depends_on: [TASK-026]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-027 — Recovery e idempotência por estágio

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Runs interrompidos são diagnosticados e retomados sem repetir efeitos concluídos ou perder trabalho.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- V0.5 aprovada na TASK-026.
- Baseline fixado no commit aprovado da TASK-026.
- Todos os efeitos externos emitem started/outcome persistidos.

## Arquivos permitidos

- `src/ai_software_factory/core/idempotency.py`
- `src/ai_software_factory/application/recovery.py`
- `src/ai_software_factory/application/orchestrator.py`
- `src/ai_software_factory/cli.py`
- `migrations/**`
- `tests/unit/test_recovery_policy.py`
- `tests/chaos/test_recovery_boundaries.py`
- `docs/runbooks/recovery.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `RecoveryPolicy.decide(snapshot: RunSnapshot) -> RecoveryAction` | Tabela total por stage/effect; pure e fail-closed. |
| `IdempotencyKey` | run+task+stage+effect+ordinal; unique no ledger. |
| `aif diagnose RUN-ID` / `aif resume RUN-ID` | Diagnose read-only; resume aplica exatamente a ação persistida. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `unknown_boundary` | Escalated; nenhuma repetição |
| `completed_effect` | nunca reexecutar |
| `existing_worktree` | reutilizar somente identidade/base/task exatas |
| `cleanup_on_recovery` | false |
| `resume_attempts` | 1 por comando |

## Passos de implementação

1. Mapear tabela stage/effect→ação e idempotency keys.
2. Persistir efeito started/completed/failed com uniqueness.
3. Implementar diagnose/resume por services existentes.
4. Criar kill points em cada boundary e upgrade/backup recovery tests.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Resume repetir commit/tool/process | Idempotency key e revalidação de identidade/autorização | `test_resume_never_duplicates_completed_effect` |

## Critérios de aceite

- [ ] **AC-001** — Repetir resume em cada kill point suportado não duplica run/worktree/attempt/package/gate/review/approval/commit.
- [ ] **AC-002** — Worktree/artifact/hash/trust profile divergente escala sem executar efeito.
- [ ] **AC-003** — Diagnose explica ação; backup/restore e upgrade preservam history/idempotency.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/chaos/test_recovery_boundaries.py::test_resume_never_duplicates_completed_effect -q` | unique effect counts | boundary matrix + ledger |
| AC-002 | `uv run pytest tests/chaos/test_recovery_boundaries.py::test_identity_mismatch_fails_closed -q` | zero external calls | diagnostic artifact |
| AC-003 | `uv run pytest tests/chaos/test_recovery_boundaries.py::test_backup_restore_and_upgrade -q` | snapshots equivalentes | backup hash + schema versions |

## Validação manual no terminal

1. `uv run aif diagnose <RUN-ID>`
   Esperado: Explica a única ação de recovery segura sem efeito externo.
2. `uv run aif resume <RUN-ID>`
   Esperado: Retoma uma vez sem duplicar efeitos já concluídos.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-027` antes de publicar o draft PR.

## Fora de escopo

Alta disponibilidade, processo remoto, cancelamento estruturado e scheduler paralelo.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
