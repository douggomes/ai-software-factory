---
title: "TASK-002 — Contrato de SPEC e validação fail-fast"
task_id: TASK-002
release: "V0.1"
status: planned
depends_on: [TASK-001]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-002 — Contrato de SPEC e validação fail-fast

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

O usuário valida uma SPEC canônica antes de criar runtime, worktree ou consumir provider.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-001 aprovada; `uv run aif --version` retorna `0`.
- Baseline é o commit aprovado da TASK-001.
- Diretórios `schemas/` e `examples/` existem.

## Arquivos permitidos

- `src/ai_software_factory/core/spec_models.py`
- `src/ai_software_factory/application/spec_parser.py`
- `src/ai_software_factory/application/spec_validator.py`
- `src/ai_software_factory/cli.py`
- `schemas/software-spec.v1.schema.json`
- `examples/specs/**`
- `tests/unit/test_spec_parser.py`
- `tests/property/test_spec_parser.py`
- `docs/spec-contract.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `SpecParser.parse(text: str) -> SoftwareSpec` | Parser puro; nunca toca filesystem, rede ou subprocesso. |
| `SpecValidator.validate(spec: SoftwareSpec, task_id: TaskId | None) -> ValidationReport` | IDs, ACs, scopes, comandos e DAG validados. |
| `aif spec validate PATH [--task ID] [--json]` | Exit `0` válido; `2` input/contrato inválido; sem runtime. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `schema_version` | `1` |
| `max_spec_bytes` | 1_048_576 |
| `max_tasks` | 200 |
| `max_dependency_depth` | 50 |
| `validation_command` | array não vazio de strings; shell string proibida |

## Passos de implementação

1. Definir modelos imutáveis e schema v1.
2. Implementar parser de frontmatter seguro e seções Markdown fechadas.
3. Validar IDs, referências, allowed scope e DAG com erros estáveis.
4. Adicionar golden, property e abuse tests; ligar comando CLI.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Parser executar payload ou aceitar traversal | Loader seguro, limites e canonicalização | `test_rejects_unsafe_frontmatter_and_traversal` |

## Critérios de aceite

- [ ] **AC-001** — SPEC válida produz JSON canônico idêntico em repetições.
- [ ] **AC-002** — Ciclo, AC duplicado, scope vazio, shell string, excesso e traversal falham com exit `2`.
- [ ] **AC-003** — Validação nunca cria `.aifactory`, worktree ou chamada externa.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/unit/test_spec_parser.py::test_valid_spec_is_canonical -q` | bytes iguais em duas execuções | snapshot `software-spec.v1.json` |
| AC-002 | `uv run pytest tests/property/test_spec_parser.py -q` | todos os inputs hostis rejeitados sem crash | relatório property tests |
| AC-003 | `uv run pytest tests/unit/test_spec_parser.py::test_validate_has_no_external_effects -q` | spy de filesystem/process/provider permanece zerado | saída pytest + spy snapshot |

## Fora de escopo

Decomposição por LLM, atualização de status dentro da SPEC e Markdown arbitrário.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
