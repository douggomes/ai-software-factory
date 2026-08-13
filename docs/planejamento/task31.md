---
title: "TASK-031 — Qualificação ampliada e release V1.1"
task_id: TASK-031
release: "V1.1"
status: planned
depends_on: [TASK-030]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-031 — Qualificação ampliada e release V1.1

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

A V1.1 é entregue com dataset ampliado, evidência, supply-chain assurance, documentação operacional, pesquisa oficial controlada, governança greenfield e limites explícitos.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-030 aprovada com scheduler isolado.
- Baseline fixado no commit aprovado da TASK-030.
- Todas as releases anteriores possuem dossiers e raw evidence.
- O dossier V0.5 referencia os manifests/evidências aprovados das TASK-033/TASK-034.

## Arquivos permitidos

- `benchmarks/datasets/v1.1/**`
- `tests/release/test_v1_1.py`
- `docs/releases/v1.1.md`
- `docs/benchmark-results/v1.1/**`
- `docs/runbooks/**`
- `README.md`
- `CHANGELOG.md`
- `dist/**`
- `artifacts/release/**`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `PR suite` | Offline: unit/contract/infrastructure/E2E/security/chaos sem tokens. |
| `Release suite` | 20 tasks uma vez + 5 estratificadas três vezes nas arquiteturas escolhidas. |
| `Research suite` | 20×3×arquiteturas somente opt-in com budget/quota explícitos. |
| `Release dossier` | Requirement→task→test→evidence; commit/lock/config/SBOM/build hashes, documentação confiável, profiles greenfield e approval. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `dataset_size` | 20 |
| `release_repetitions` | 5 tasks × 3 |
| `research` | disabled |
| `supported_python` | 3.13 e 3.14 |
| `SBOM` | CycloneDX |
| `release_authority` | humano; agente não tag/push |

## Passos de implementação

1. Expandir dataset/manifest com commits-base e trust classification.
2. Executar PR/release suites e comparar V1.0 serial/static contra V1.1.
3. Executar lock/audit/secret/SAST/SBOM/provenance/build/upgrade/rollback checks.
4. Atualizar docs/runbooks/changelog e produzir dossier para aprovação humana.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Release declarar autonomia/segurança além da evidência | Rastreabilidade completa e limitations obrigatórias | `test_release_dossier_has_complete_traceability` |

## Critérios de aceite

- [ ] **AC-001** — 20 tasks e repetições definidas geram raw results com média, dispersão, sample size e failure categories.
- [ ] **AC-002** — PR suite offline e gates de arquitetura/typing/test/security/supply chain passam em Python 3.13/3.14.
- [ ] **AC-003** — Dossier contém SBOM/provenance/checksums/threat-model/rollback/limitations, evidências TASK-033/TASK-034 íntegras e aprovação humana pendente exata.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/release/test_v1_1.py::test_dataset_and_statistics_are_traceable -q` | raw results e estatística descritiva válidos | results.json + report.md |
| AC-002 | `uv run pytest tests/release/test_v1_1.py::test_quality_security_and_supply_chain_gates -q` | todos os gates/suppressions policy aprovados | gate bundle + SBOM |
| AC-003 | `uv run pytest tests/release/test_v1_1.py::test_release_dossier_has_complete_traceability -q` | matriz sem lacunas, inclusive gateway/governança, e hashes verificáveis | release dossier + checksums |

## Validação manual no terminal

1. `uv run pytest tests/release/test_v1_1.py -q`
   Esperado: Dataset, rastreabilidade, supply chain e release dossier passam.
2. `uv build`
   Esperado: Gera wheel/sdist verificáveis correspondentes ao lock e provenance da V1.1.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-031` antes de publicar o draft PR.

## Fora de escopo

Tag/push/merge pelo agente, SLA remoto, multiusuário, autonomia total e generalização além do dataset.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
