---
title: "TASK-035 — Snapshot e evidência segura de avaliação"
task_id: TASK-035
release: "V0.1"
status: ready
depends_on: [TASK-032]
baseline_commit: "3ee145836564ca56ca583e3b0878eb7c522af0a4"
risk_level: critical
---

# TASK-035 — Snapshot e evidência segura de avaliação

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md),
> [engineering-standards.md](engineering-standards.md),
> [security-review.md](security-review.md) e
> [ADR-0006](../adr/0006-strong-isolation-for-validation.md). O agente não pode
> ampliar paths, autoridade, rede, budget ou defaults.

## Valor entregue

A Factory materializa um snapshot verificável do worktree autorizado, captura
status/diff/ignored/binário sem confused deputy e sanitiza output em streaming
antes da persistência. Esta fatia não executa código não confiável.

## Definition of Ready

- [x] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [x] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [x] Todas as precondições abaixo foram verificadas.
- [x] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [x] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-032 e o ADR-0006 estão integrados em `dev` pelo merge `3ee145836564ca56ca583e3b0878eb7c522af0a4`.
- `ProcessRunner`, `ArtifactStore`, `WorkspaceManager` e seus contract tests estão aprovados.
- Baseline fixado no merge commit `3ee145836564ca56ca583e3b0878eb7c522af0a4` de `origin/dev`.
- Fixtures Git incluem arquivo ignored, binário, symlink, canários e writer concorrente.

## Arquivos permitidos

- `src/ai_software_factory/core/process_models.py`
- `src/ai_software_factory/core/evaluation_workspace.py`
- `src/ai_software_factory/ports/processes.py`
- `src/ai_software_factory/ports/evaluation_workspace.py`
- `src/ai_software_factory/ports/output_sanitization.py`
- `src/ai_software_factory/adapters/process/asyncio_runner.py`
- `src/ai_software_factory/adapters/process/output_sanitizer.py`
- `src/ai_software_factory/adapters/git/evaluation_workspace.py`
- `src/ai_software_factory/cli.py`
- `tests/contract/processes/**`
- `tests/contract/evaluation_workspace/**`
- `tests/contract/workspace/test_workspace_manager_contract.py`
- `tests/integration/test_process_runner.py`
- `tests/integration/test_process_output_sanitizer.py`
- `tests/integration/test_evaluation_workspace.py`
- `tests/integration/test_git_worktree.py`
- `tests/security/__init__.py`
- `tests/security/test_evaluation_workspace.py`
- `docs/runbooks/evaluation-workspace.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado. Nenhuma
dependência Python nova é autorizada; a implementação usa somente stdlib e as
portas já aprovadas.

## Arquivos proibidos

- `docs/planejamento/**`, `docs/adr/**`, `AGENTS.md`
- `.env*`, `**/auth.json`, keychain, tokens, chaves e credenciais
- socket Docker/Podman, `$HOME`, agent sockets ou paths fora da raiz autorizada
- execução de compile, lint, types, tests ou qualquer código do repositório
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `EvaluationWorkspace.capture(request) -> EvaluationSnapshot` | Canonicaliza identidade/raiz, captura inventário limitado sem symlink e produz manifest imutável com SHA-256. |
| `EvaluationSnapshot` | ID, base/diff identity, root privado, manifest ref/hash e lifecycle explícito; nunca contém segredo ou Git metadata bruta. |
| `RepositoryInspection.inspect(snapshot) -> RepositoryEvidence` | Produz status/diff/ignored/binário limitados sobre o snapshot e evidencia tipo+path+fingerprint sem valor secreto. |
| `OutputSanitizer.feed(bytes) -> bytes` | Streaming limitado e canônico; redige segredo explícito, assignments, private keys e credenciais cloud mesmo entre chunks. |

`EvaluationWorkspace`, `RepositoryInspection` e `OutputSanitizer` são portas
ISP; adapters Git/process são ligados somente no composition root. A CLI não
implementa subprocesso, Git, cópia de filesystem ou redaction.

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `evaluation.max_files` | 100000 |
| `evaluation.max_total_bytes` | 1073741824 |
| `evaluation.symlinks` | deny, inclusive componentes intermediários |
| `evaluation.concurrent_change` | invalida snapshot e avaliação |
| `evaluation.git_scope` | inventário completo limitado inclui tracked, untracked e ignored; `.git` é excluído |
| `evaluation.secret_evidence` | tipo+path+fingerprint; conteúdo e valor são proibidos |
| `output.raw_access` | proibido; somente refs sanitizadas e hashes cruzam a porta |

## Passos de implementação

1. Fechar modelos/portas imutáveis de snapshot, inventário e sanitização.
2. Extrair sanitização streaming do runner e impedir retorno/persistência de bytes brutos.
3. Implementar inspeção/materialização segura do worktree fora da CLI, sem seguir symlink.
4. Vincular manifest, base/diff identity e artifacts por hashes verificados na leitura.
5. Cobrir contracts, TOCTOU, path do DB, ignored/binário, limites e output hostil.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| DB/path/symlink aponta para repo externo | identidade esperada, canonicalização por componente e openat/no-follow | `test_external_or_swapped_worktree_is_rejected` |
| Writer troca conteúdo durante captura | lock, manifest antes/depois e snapshot privado | `test_concurrent_writer_invalidates_snapshot` |
| Ignored/binário esconde credencial ou segredo | inventário completo limitado e scanner por bytes | `test_ignored_binary_and_credential_paths_fail_closed` |
| Segredo cru cruza chunks ou vira artifact | sanitizador único antes da porta/store | `test_private_key_cloud_token_and_split_canary_are_redacted` |

## Critérios de aceite

- [ ] **AC-001** — Snapshot canonicalizado vincula repo/run/task, base/diff identity e hashes; path persistido externo, symlink ou troca de componente falha antes de leitura/cópia.
- [ ] **AC-002** — Inventário limitado cobre tracked, untracked, ignored e binário; credencial/segredo gera somente tipo+path+fingerprint e nunca conteúdo bruto.
- [ ] **AC-003** — Writer concorrente ou divergência entre manifest/conteúdo invalida a captura, e nenhum comando de avaliação toca o worktree original.
- [ ] **AC-004** — Output excessivo ou hostil é limitado e sanitizado entre chunks antes da persistência, sem canário, private key ou token cloud nos refs/artifacts/erros.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/security/test_evaluation_workspace.py::test_external_symlink_and_swapped_worktree_fail_closed -q` | todos os aliases/escapes falham antes de leitura | erro de domínio sanitizado sem host path |
| AC-002 | `uv run pytest tests/integration/test_evaluation_workspace.py::test_inventory_covers_ignored_binary_and_secret_evidence -q` | inventário completo; canários ausentes da evidência | manifest + findings tipo/path/fingerprint |
| AC-003 | `uv run pytest tests/integration/test_evaluation_workspace.py::test_snapshot_identity_hash_and_toctou -q` | writer e hash divergente invalidam; origem permanece igual | manifest/hash do fixture seguro |
| AC-004 | `uv run pytest tests/integration/test_process_output_sanitizer.py::test_streaming_sanitizer_redacts_structured_and_split_secrets -q` | limites e redaction ocorrem antes do store | ProcessResult/artifact refs sanitizados |

## Validação manual no terminal

1. `uv run pytest tests/contract/evaluation_workspace tests/security/test_evaluation_workspace.py -q`
   Esperado: snapshots válidos são reproduzíveis e todos os escapes de path/symlink/TOCTOU falham fechados.
2. `uv run pytest tests/integration/test_process_output_sanitizer.py::test_streaming_sanitizer_redacts_structured_and_split_secrets -q`
   Esperado: nenhum canário, private key ou token cloud aparece em artifacts ou erro sanitizado.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-035`
antes de publicar o draft PR.

## Fora de escopo

Execução de gates, container/VM, imagem OCI, configuração de runtime, network,
comandos da CLI e qualquer fallback para código não confiável no host.

## Evidência de conclusão

Contract/security reports, manifest/snapshot fixtures, runbook e relatório
obrigatório de [AGENTS.md](../../AGENTS.md)
contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais,
revisão canônica e riscos residuais. Após os gates, o agente cria commit,
publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando
`gh`. Nenhum output bruto, host path ou segredo entra na evidência.
