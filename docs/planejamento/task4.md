---
title: "TASK-004 — Ledger SQLite transacional e migrations"
task_id: TASK-004
release: "V0.1"
status: done
depends_on: [TASK-003]
baseline_commit: "78906ac116925f30daaa57131856ab825bb3d5f2"
risk_level: high
---

# TASK-004 — Ledger SQLite transacional e migrations

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Estado e eventos sobrevivem a reinício e são gravados atomicamente em SQLite versionado.

## Definition of Ready

- [x] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [x] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [x] Todas as precondições abaixo foram verificadas.
- [x] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [x] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-003 aprovada com modelos/eventos estáveis.
- Baseline fixado no commit aprovado da TASK-003.
- SQLite disponível segundo `aif doctor`.

## Arquivos permitidos

- `src/ai_software_factory/ports/persistence.py`
- `src/ai_software_factory/adapters/persistence/sqlite.py`
- `src/ai_software_factory/adapters/persistence/schema.py`
- `migrations/**`
- `tests/contract/persistence/**`
- `tests/integration/test_sqlite_store.py`
- `docs/adr/0002-sqlite-operational-source-of-truth.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `RunStore.create_run(run: Run, event: DomainEvent) -> None` | Estado e evento na mesma transação. |
| `RunStore.transition(run_id: RunId, task_id: TaskId, transition: Transition) -> None` | Identidade composta run_id+task_id; optimistic version check; conflito explícito. Revisado na correção QA-004-001 para impedir que dois runs com o mesmo TaskId se contaminem. |
| `RunStore.load_run(run_id: RunId) -> RunSnapshot` | Reconstrói estado sem depender de NDJSON. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `journal_mode` | WAL |
| `foreign_keys` | ON |
| `busy_timeout_ms` | 5000 |
| `session_scope` | uma `AsyncSession` por unidade concorrente |
| `sql` | sempre parametrizado |

## Passos de implementação

1. Definir porta sem tipos SQLAlchemy.
2. Criar schema/migration inicial com constraints e versão.
3. Implementar adapter assíncrono com transações curtas.
4. Criar contract suite e testes de rollback, contention e upgrade.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Dual write ou corrupção concorrente | SQLite autoritativo e transação estado+evento | `test_event_failure_rolls_back_transition` |

## Critérios de aceite

- [x] **AC-001** — Run criado pode ser carregado após fechar e reabrir o processo/store.
- [x] **AC-002** — Falha ao gravar evento reverte a transição completa.
- [x] **AC-003** — Migration vazio/upgrade e acesso concorrente por sessões separadas passam.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_sqlite_store.py::test_persists_across_reopen -q` | snapshot reconstruído igual | DB fixture + snapshot |
| AC-002 | `uv run pytest tests/integration/test_sqlite_store.py::test_event_failure_rolls_back_transition -q` | estado/version/event count inalterados | relatório pytest |
| AC-003 | `uv run pytest tests/contract/persistence tests/integration/test_sqlite_store.py::test_concurrent_sessions -q` | migrations e concorrência aprovadas | saída pytest + versão schema |

## Validação manual no terminal

1. `uv run pytest tests/integration/test_sqlite_store.py::test_persists_across_reopen -q`
   Esperado: O run é recuperado após fechar e reabrir o store.
2. `uv run pytest tests/integration/test_sqlite_store.py::test_event_failure_rolls_back_transition -q`
   Esperado: A falha do evento não deixa transição parcial.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-004` antes de publicar o draft PR.

## Fora de escopo

Artifact files, export NDJSON, CLI status e paralelismo de scheduler.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
