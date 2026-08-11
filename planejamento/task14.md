---
title: "TASK-014 — Qualificação e release V0.1"
task_id: TASK-014
release: "V0.1"
status: planned
depends_on: [TASK-013]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-014 — Qualificação e release V0.1

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

A primeira release demonstra pipeline, gates e failover com evidência reproduzível; smoke real permanece controlado.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-001 a TASK-013 aprovadas.
- Baseline fixado no commit aprovado da TASK-013.
- Nenhum smoke real é obrigatório para suite offline.

## Arquivos permitidos

- `docs/releases/v0.1.md`
- `docs/runbooks/first-run.md`
- `examples/specs/v0.1-demo.md`
- `tests/release/test_v0_1.py`
- `README.md`
- `CHANGELOG.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `tests/release/test_v0_1.py` | Agrega apenas suites existentes; não duplica regras. |
| `docs/releases/v0.1.md` | Commit/config/lock hashes, versões, AC→evidência e limitations. |
| `first-run.md` | Comandos offline/fake completos; live claramente opt-in. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `release_gate` | offline obrigatório |
| `live_smoke` | opt-in e não bloqueante por ausência de quota |
| `tagging` | humano; agente proibido |
| `supported_python` | 3.13 e 3.14 |

## Passos de implementação

1. Criar SPEC demo e teste agregado V0.1.
2. Executar ambiente limpo, gates globais e E2E failover.
3. Produzir runbook e release dossier com hashes.
4. Revisar segurança/known limitations; não criar tag.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Release baseada em relato sem reprodução | Dossier liga cada claim a comando/artifact | `test_v0_1_release_gate` |

## Critérios de aceite

- [ ] **AC-001** — Suite V0.1 offline reproduz bootstrap, SPEC, ledger, worktree, gates, fake E2E e continuação.
- [ ] **AC-002** — Contract OpenCode passa offline e smoke real está ausente da suite padrão.
- [ ] **AC-003** — Dossier contém hashes, versões, comandos, evidências, limitações e aprovação pendente humana.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/release/test_v0_1.py -q` | todos os componentes V0.1 exercitados | JUnit/coverage + run report |
| AC-002 | `uv run pytest tests/contract/agents/opencode -q -m 'not live'` | zero processo/provider live | pytest collection report |
| AC-003 | `python3 scripts/validate_tasks.py && uv run ruff check src tests` | documentação/contratos e código válidos | release dossier + gates |

## Fora de escopo

Tag/push/merge, providers adicionais, review semântico e benchmark.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
