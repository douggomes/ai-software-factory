---
title: "TASK-026 — Dataset, hidden tests e release V0.5"
task_id: TASK-026
release: "V0.5"
status: planned
depends_on: [TASK-025]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-026 — Dataset, hidden tests e release V0.5

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Cinco tasks reais medem arquiteturas A/B/C sem vazar hidden tests ou executar origem não confiável no host, e o dossier V0.5 comprova também o gateway documental e o bootstrap greenfield.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-025 aprovada com harness fake.
- Baseline fixado no commit aprovado da TASK-025.
- Factory-lab possui commits-base revisados e trust classification explícita.
- Evidências aprovadas da TASK-033 e da TASK-034 estão referenciáveis por commit, schema e hash.

## Arquivos permitidos

- `benchmarks/datasets/v0.5/**`
- `tests/security/test_hidden_test_isolation.py`
- `tests/release/test_v0_5.py`
- `docs/releases/v0.5.md`
- `docs/benchmark-results/v0.5/**`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `dataset v0.5` | Feature, bugfix, tests, refactor e security/idempotency; cada uma com commit SHA. |
| `HiddenTestProvider` config | Root privada fora do worktree; entregue somente ao evaluator após worker. |
| `V0.5 report` | Raw results, sample size, first/final pass, repairs, failures, limitations e matriz de evidências TASK-033/TASK-034. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `dataset_size` | 5 |
| `repetitions` | 1 por A/B/C na release |
| `hidden_visibility` | evaluator-only após worker |
| `untrusted_repo` | exige isolamento forte; ausência fail-closed |
| `claims` | descritivas; sem significância forte |

## Passos de implementação

1. Versionar manifest/commits-base e critérios das cinco tasks.
2. Implementar/configurar hidden test injection fora do contexto.
3. Executar security isolation e A/B/C com budgets iguais.
4. Verificar evidence/schema hashes do gateway documental e golden manifests/profiles do bootstrap.
5. Produzir raw results e dossier V0.5 sem extrapolação.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Hidden test vazar ou repo comprometer host | Evaluator-only e isolamento forte/fail-closed | `test_worker_cannot_discover_hidden_tests_or_host` |
| Release omitir segurança documental ou governança greenfield | Dossier exige evidência pinada das TASK-033/TASK-034 | `test_release_requires_documentation_and_governance_evidence` |

## Critérios de aceite

- [ ] **AC-001** — Worker/context/MCP/telemetry não conseguem listar, ler ou inferir hidden tests antes da avaliação.
- [ ] **AC-002** — Traversal/symlink/hook/subprocess do dataset não alcança home/hidden tests; untrusted sem sandbox falha.
- [ ] **AC-003** — Cinco commits-base executam A/B/C com raw results e relatório/dossier reproduzíveis.
- [ ] **AC-004** — Dossier rejeita ausência, hash divergente ou schema incompatível nas evidências da TASK-033/TASK-034.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/security/test_hidden_test_isolation.py::test_worker_cannot_discover_hidden_tests_or_host -q` | zero paths/content leaked | context/tool/telemetry scans |
| AC-002 | `uv run pytest tests/security/test_hidden_test_isolation.py::test_untrusted_dataset_requires_strong_isolation -q` | host canaries intactos e fail-closed | isolation capability report |
| AC-003 | `uv run pytest tests/release/test_v0_5.py -q` | dataset/hash/result schemas aprovados | results.json + dossier V0.5 |
| AC-004 | `uv run pytest tests/release/test_v0_5.py::test_release_requires_documentation_and_governance_evidence -q` | evidence e governance manifests pinados e íntegros | matriz TASK-033/TASK-034 no dossier |

## Validação manual no terminal

1. `uv run pytest tests/security/test_hidden_test_isolation.py -q`
   Esperado: Hidden tests e canários do host permanecem invisíveis ao worker.
2. `uv run pytest tests/release/test_v0_5.py -q`
   Esperado: As cinco tasks, arquiteturas A/B/C, evidências documentais e profiles greenfield passam o gate V0.5.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-026` antes de publicar o draft PR.

## Fora de escopo

20 tasks, inferência estatística forte, router dinâmico e execução host de repo arbitrário.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
