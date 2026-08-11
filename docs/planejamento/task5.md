---
title: "TASK-005 — ArtifactStore íntegro e consulta de execução"
task_id: TASK-005
release: "V0.1"
status: planned
depends_on: [TASK-004]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-005 — ArtifactStore íntegro e consulta de execução

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Artifacts imutáveis e consultas CLI tornam uma execução auditável sem transcript de agente.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-004 aprovada com RunStore operacional.
- Baseline fixado no commit aprovado da TASK-004.
- Diretório de runtime configurável em fixture temporária.

## Arquivos permitidos

- `src/ai_software_factory/ports/artifacts.py`
- `src/ai_software_factory/adapters/persistence/artifact_store.py`
- `src/ai_software_factory/application/queries.py`
- `src/ai_software_factory/cli.py`
- `tests/contract/artifacts/**`
- `tests/integration/test_artifact_store.py`
- `tests/integration/test_status_cli.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ArtifactStore.put(ref: ArtifactRef, data: bytes) -> StoredArtifact` | Create-exclusive, temp+atomic rename, SHA-256 e `0600`. |
| `ArtifactStore.read(ref: ArtifactRef) -> bytes` | Revalida root, owner, size e hash. |
| `aif status RUN-ID --json` / `aif events RUN-ID` | Consultas read-only; NDJSON é export derivado. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `factory_home_mode` | `0700` |
| `artifact_mode` | `0600` |
| `hash_algorithm` | SHA-256 |
| `max_artifact_bytes` | 67_108_864 |
| `overwrite` | proibido |

## Passos de implementação

1. Definir porta e referências tipadas.
2. Implementar criação segura e validação de leitura.
3. Registrar metadata no ledger sem dual source of truth.
4. Implementar queries/CLI e export NDJSON determinístico.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Symlink/tampering expor arquivo externo | Canonicalização, no-follow e hash na leitura | `test_rejects_symlink_and_tampered_artifact` |

## Critérios de aceite

- [ ] **AC-001** — Escrita interrompida não publica artifact e overwrite é rejeitado.
- [ ] **AC-002** — Symlink, path externo, owner/mode inválido e hash adulterado falham fechados.
- [ ] **AC-003** — Status/eventos sobrevivem reinício e export NDJSON é reconstruível byte a byte.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_artifact_store.py::test_atomic_create_and_no_overwrite -q` | nenhum temporário registrado | filesystem fixture |
| AC-002 | `uv run pytest tests/integration/test_artifact_store.py::test_rejects_symlink_and_tampered_artifact -q` | todas as leituras hostis rejeitadas | relatório security cases |
| AC-003 | `uv run pytest tests/integration/test_status_cli.py -q` | JSON/NDJSON golden após reopen | snapshots sanitizados |

## Validação manual no terminal

1. `uv run aif status <RUN-ID> --json`
   Esperado: Mostra o snapshot persistido do run após reiniciar a CLI.
2. `uv run aif events <RUN-ID>`
   Esperado: Exporta NDJSON reconstruível sem depender de arquivo prévio.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-005` antes de publicar o draft PR.

## Fora de escopo

Worktree, execução de processos, providers e cleanup de runs.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
