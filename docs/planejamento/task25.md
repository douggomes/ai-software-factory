---
title: "TASK-025 — Harness de benchmark reproduzível"
task_id: TASK-025
release: "V0.5"
status: planned
depends_on: [TASK-024]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-025 — Harness de benchmark reproduzível

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

A Factory valida e executa manifests de benchmark em bases Git imutáveis com resultados comparáveis e modo fake.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- V0.4 aprovada na TASK-024.
- Baseline fixado no commit aprovado da TASK-024.
- Repositório irmão factory-lab pode ser configurado sem ser criado implicitamente.

## Arquivos permitidos

- `src/ai_software_factory/benchmarks/models.py`
- `src/ai_software_factory/benchmarks/manifest.py`
- `src/ai_software_factory/benchmarks/runner.py`
- `src/ai_software_factory/benchmarks/report.py`
- `src/ai_software_factory/cli.py`
- `schemas/benchmark-manifest.v1.json`
- `schemas/benchmark-result.v1.json`
- `tests/unit/benchmarks/**`
- `tests/integration/test_benchmark_harness.py`
- `docs/benchmark.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `BenchmarkManifest v1` | Dataset/task/base commit/architecture/budget/repetitions/trust profile. |
| `BenchmarkRunner.run(manifest) -> BenchmarkResult` | Worktree novo por repetition; base verificada antes de worker. |
| `aif benchmark validate|run|report` | Validate sem efeito; run exige trust policy; report somente results. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `architecture_A` | single worker |
| `architecture_B` | worker + deterministic gates |
| `architecture_C` | gates + independent review + repair |
| `repetitions` | 1 |
| `trust_profile` | trusted-lab |
| `live` | false |

## Passos de implementação

1. Fechar schemas/manifest validation e CLI.
2. Implementar runner com base/worktree/budgets idênticos.
3. Implementar result/report com first/final pass e failure categories.
4. Criar fake dataset fixtures e reprodução/hash tests.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Comparação enviesada por base/budget diferente | Manifest fechado e verificação antes de worker | `test_repetitions_share_base_and_budget` |

## Critérios de aceite

- [ ] **AC-001** — Manifest inválido/base ausente falha antes de worktree/worker.
- [ ] **AC-002** — Repetições usam base, budget, context/profile hashes idênticos e worktrees novos.
- [ ] **AC-003** — Modo fake executa A/B/C e gera result/report v1 sem token ou provider real.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_benchmark_harness.py::test_invalid_manifest_has_no_effects -q` | spies worktree/worker zerados | validation report |
| AC-002 | `uv run pytest tests/integration/test_benchmark_harness.py::test_repetitions_share_base_and_budget -q` | identidades iguais exceto run/worktree | BenchmarkResult fixtures |
| AC-003 | `uv run pytest tests/integration/test_benchmark_harness.py::test_fake_architectures_and_report -q` | A/B/C completos offline | results.json + report.md |

## Validação manual no terminal

1. `uv run aif benchmark validate <MANIFEST-V1>`
   Esperado: Valida dataset/base/budgets sem criar worktree ou chamar worker.
2. `uv run aif benchmark report <RESULTS-JSON>`
   Esperado: Gera relatório determinístico a partir dos resultados persistidos.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-025` antes de publicar o draft PR.

## Fora de escopo

Dataset real de cinco tasks, hidden tests, conclusões estatísticas e router.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
