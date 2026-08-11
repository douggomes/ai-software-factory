---
title: "TASK-022 — Perfis de execução, fallback e release V0.3"
task_id: TASK-022
release: "V0.3"
status: planned
depends_on: [TASK-021]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-022 — Perfis de execução, fallback e release V0.3

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Papéis, workers e fallback são configuráveis por perfis fechados, e a V0.3 é reproduzível com ou sem Ollama.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-021 aprovada com planner local.
- Baseline fixado no commit aprovado da TASK-021.
- OpenCode, Codex e Claude contract suites estão verdes offline.

## Arquivos permitidos

- `src/ai_software_factory/core/profiles.py`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/application/orchestrator.py`
- `factory.example.toml`
- `examples/config/**`
- `tests/unit/test_execution_profiles.py`
- `tests/release/test_v0_3.py`
- `docs/releases/v0.3.md`
- `docs/runbooks/local-planner.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ExecutionProfile` | Mapeia role→ordered workers, authority, cost/network policy e fallback. |
| `ProfileResolver.resolve(name: str, capabilities: Snapshot) -> ResolvedProfile` | Determinístico e explicável; config inválida falha no preflight. |
| `planner fallback` | Ollama ausente → `DeterministicMinimalPlan`; nunca escolhe provider pago oculto. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `default_profile` | subscription-safe |
| `offline` | fakes + Ollama opcional; rede externa deny |
| `subscription-safe` | sem API key incremental |
| `benchmark` | budget explícito; nunca default |
| `planner_fallback` | deterministic-minimal |

## Passos de implementação

1. Fechar modelos/profiles e exemplos TOML completos.
2. Implementar resolver/fallback sem branches de provider no Core.
3. Testar matriz de capabilities/custo/ausência Ollama.
4. Executar release gate e produzir dossier V0.3.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Fallback ocultar custo ou elevar worker | Perfis fechados e decisão persistida | `test_fallback_never_enables_unlisted_worker_or_cost` |

## Critérios de aceite

- [ ] **AC-001** — Cada perfil resolve os mesmos workers/autoridades para o mesmo snapshot e explica fallback.
- [ ] **AC-002** — Ausência de Ollama usa plano mínimo; nenhuma API key/custo/rede não declarada é ativada.
- [ ] **AC-003** — Suite V0.3 comprova contexto, Claude, Ollama fake e profiles com dossier reproduzível.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/test_execution_profiles.py::test_profiles_are_deterministic_and_explained -q` | goldens por profile | ResolvedProfile JSON |
| AC-002 | `uv run pytest tests/unit/test_execution_profiles.py::test_fallback_never_enables_unlisted_worker_or_cost -q` | spies de custo/rede zerados | fallback decision |
| AC-003 | `uv run pytest tests/release/test_v0_3.py -q` | release gate offline aprovado | dossier V0.3 + hashes |

## Fora de escopo

Router histórico, download de modelo, perfis arbitrários e release/tag pelo agente.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
