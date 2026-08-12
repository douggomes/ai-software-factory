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
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md), [security-review.md](security-review.md) e [ADR-0005](../adr/0005-cloud-only-model-runtime.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Papéis, workers cloud e fallback são configuráveis por perfis fechados, e a
V0.3 é reproduzível sem chamada live na suite padrão.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-021 aprovada com planner cloud agnóstico.
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
- `docs/runbooks/cloud-planner.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ExecutionProfile` | Mapeia role→ordered workers, authority, cost/network policy e fallback. |
| `ProfileResolver.resolve(name: str, capabilities: Snapshot) -> ResolvedProfile` | Determinístico e explicável; config inválida falha no preflight. |
| `planner fallback` | nenhum worker cloud elegível/disponível → `DeterministicMinimalPlan`; nunca escolhe provider ou custo oculto. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `default_profile` | subscription-safe |
| `offline` | somente fakes/fixtures; zero inferência ou rede de provider |
| `subscription-safe` | CLIs cloud com sessão oficial; sem API key incremental gerida pela Factory |
| `benchmark` | budget explícito; nunca default |
| `planner_fallback` | deterministic-minimal |
| `inference_mode` | cloud-only; endpoint local/self-hosted deny |
| `data_egress` | context view mínima; provider, classificação e retention explícitos no profile |

## Passos de implementação

1. Fechar modelos/profiles e exemplos TOML completos.
2. Implementar resolver/fallback sem branches de provider no Core.
3. Testar matriz de capabilities, custo e indisponibilidade dos workers cloud.
4. Executar release gate e produzir dossier V0.3.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Fallback ocultar custo ou elevar worker | Perfis fechados e decisão persistida | `test_fallback_never_enables_unlisted_worker_or_cost` |

## Critérios de aceite

- [ ] **AC-001** — Cada perfil resolve os mesmos workers/autoridades para o mesmo snapshot e explica fallback.
- [ ] **AC-002** — Ausência de worker cloud elegível usa plano mínimo; nenhum endpoint local, API key, custo ou rede não declarada é ativado.
- [ ] **AC-003** — Suite V0.3 comprova contexto, fixtures OpenCode/Codex/Claude, planner fake e profiles com dossier reproduzível.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/test_execution_profiles.py::test_profiles_are_deterministic_and_explained -q` | goldens por profile | ResolvedProfile JSON |
| AC-002 | `uv run pytest tests/unit/test_execution_profiles.py::test_fallback_never_enables_unlisted_worker_or_cost -q` | spies de custo/rede zerados | fallback decision |
| AC-003 | `uv run pytest tests/release/test_v0_3.py -q` | release gate offline aprovado | dossier V0.3 + hashes |

## Validação manual no terminal

1. `uv run pytest tests/unit/test_execution_profiles.py::test_profiles_are_deterministic_and_explained -q`
   Esperado: Perfis resolvem workers/autoridades e fallback de modo estável.
2. `uv run pytest tests/release/test_v0_3.py -q`
   Esperado: O gate offline da V0.3 passa sem chamada live e rejeita configuração de inferência local/self-hosted.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-022` antes de publicar o draft PR.

## Fora de escopo

Router histórico, inferência local/self-hosted, download de modelo, perfis arbitrários e release/tag pelo agente.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
