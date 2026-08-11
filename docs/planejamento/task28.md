---
title: "TASK-028 — Cancellation, chaos, hardening e release V1.0"
task_id: TASK-028
release: "V1.0"
status: planned
depends_on: [TASK-027]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-028 — Cancellation, chaos, hardening e release V1.0

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

A Factory encerra grupos de trabalho com segurança, suporta falhas adversariais e entrega V1.0 adequada a laboratório local sério.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-027 aprovada com recovery por boundary.
- Baseline fixado no commit aprovado da TASK-027.
- Threat model atual e findings possuem owner/disposição.

## Arquivos permitidos

- `src/ai_software_factory/application/cancellation.py`
- `src/ai_software_factory/application/orchestrator.py`
- `src/ai_software_factory/adapters/process/asyncio_runner.py`
- `tests/chaos/**`
- `tests/security/**`
- `tests/release/test_v1_0.py`
- `docs/runbooks/cancellation.md`
- `docs/releases/v1.0.md`
- `docs/planejamento/security-review.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**` exceto o `security-review.md` listado explicitamente nos arquivos permitidos
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `CancellationService.cancel(run_id, reason) -> CancellationReport` | Cancela TaskGroup/process groups, persiste outcome e preserva worktree. |
| `ChaosPoint` | Enum test-only em boundaries versionadas; proibido em runtime padrão. |
| `V1.0 dossier` | Threat model, chaos matrix, vulnerabilities/suppressions e recovery evidence. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `SIGINT_SIGTERM` | cancelamento estruturado |
| `child_termination` | TERM 5s → KILL |
| `lock_wait` | timeout explícito; nunca infinito |
| `temporary_artifact` | inválido e removível somente após diagnóstico |
| `release_scope` | trusted-lab |

## Passos de implementação

1. Implementar cancellation service e integrar ProcessRunner/Orchestrator.
2. Completar chaos matrix: signals, DB locked, partial JSON, artifact/tamper, worktree, reviewer.
3. Executar abuse/security regressions e revisar threat model.
4. Executar gate V1.0 e produzir dossier/known limitations.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Cancelamento deixar órfão/corromper estado | Structured concurrency e persisted cancellation | `test_signal_cancels_children_and_preserves_evidence` |

## Critérios de aceite

- [ ] **AC-001** — SIGINT/SIGTERM encerram filhos, persistem Cancelled e preservam worktree/evidência retomável.
- [ ] **AC-002** — Chaos/security matrix cobre DB lock, partial output, tamper, symlink, TOCTOU, canary e isolation failure.
- [ ] **AC-003** — V1.0 passa upgrade/recovery/gates e documenta trusted-lab, findings e riscos residuais.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/chaos/test_cancellation.py::test_signal_cancels_children_and_preserves_evidence -q` | zero órfãos e state correto | PID/state/artifact report |
| AC-002 | `uv run pytest tests/chaos tests/security -q` | matriz completa aprovada | chaos/security reports |
| AC-003 | `uv run pytest tests/release/test_v1_0.py -q` | release gate e dossier aprovados | dossier V1.0 + hashes |

## Validação manual no terminal

1. `uv run pytest tests/chaos tests/security -q`
   Esperado: Toda a matriz chaos/security passa sem órfãos ou perda de evidência.
2. `uv run pytest tests/release/test_v1_0.py -q`
   Esperado: Upgrade, recovery e hardening aprovam a V1.0 trusted-lab.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-028` antes de publicar o draft PR.

## Fora de escopo

Alta disponibilidade, multiusuário, SLA remoto, merge automático e execução de repo arbitrário no host.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
