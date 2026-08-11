---
title: "TASK-001 — Bootstrap reproduzível e diagnóstico offline"
task_id: TASK-001
release: "V0.1"
status: ready
depends_on: []
baseline_commit: "UNBORN"
risk_level: medium
---

# TASK-001 — Bootstrap reproduzível e diagnóstico offline

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Um agente parte da casca versionável, sincroniza o ambiente e entrega uma CLI instalável com diagnóstico local que não consome quota.

## Definition of Ready

- [x] Não há dependências anteriores.
- [x] `baseline_commit: UNBORN` é a exceção de bootstrap autorizada.
- [x] Python, uv, Git e o validador documental estão disponíveis.
- [x] Interfaces, defaults e paths deste contrato estão fechados.
- [x] Não existe outra task `ready`.

## Precondições

- `python3 --version`, `uv --version` e `git --version` retornam `0`.
- A raiz é `/Users/douglasgomes/Projetos/ai-software-factory` e ainda pode ser um repositório Git unborn.
- `python3 scripts/validate_tasks.py` retorna `0` antes das edições.

## Arquivos permitidos

- `pyproject.toml`
- `uv.lock`
- `.python-version`
- `.gitignore`
- `LICENSE`
- `README.md`
- `factory.example.toml`
- `src/ai_software_factory/__init__.py`
- `src/ai_software_factory/cli.py`
- `src/ai_software_factory/config.py`
- `tests/unit/test_config.py`
- `tests/integration/test_doctor.py`
- `docs/adr/0001-cli-workers-not-provider-apis.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `aif --version` | Imprime somente a versão e retorna `0`. |
| `aif doctor --json` | JSON estável com Python, uv, Git, SQLite e providers; probes read-only; nenhum modelo chamado. |
| `Settings.load(path: Path | None) -> Settings` | TOML estrito; campos desconhecidos falham antes de efeitos. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `python` | >=3.13,<3.15; `.python-version` = 3.14 |
| `config_path` | `./factory.toml`; ausência usa defaults seguros |
| `no_incremental_cost` | `true` |
| `live_probes` | `false`; somente `--live` autoriza smoke |

## Passos de implementação

1. Completar metadados/dependências e lock do projeto `uv` sem instalar ferramentas globalmente.
2. Implementar configuração estrita e entry point `aif`.
3. Implementar probes offline com timeout e saída sanitizada.
4. Configurar Ruff security, Pyright strict, pytest, import-linter, pip-audit e detect-secrets; documentar comandos.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Diagnóstico vazar ambiente ou consumir provider | Allowlist de campos e `--live` explícito | `test_doctor_offline_never_invokes_provider` |

## Critérios de aceite

- [ ] **AC-001** — `uv sync --locked` e `aif --version` funcionam em checkout limpo.
- [ ] **AC-002** — `aif doctor --json` é determinístico, offline e representa provider ausente como `unavailable`.
- [ ] **AC-003** — Config inválida falha antes de efeitos e todos os gates de bootstrap passam.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv sync --locked && uv run aif --version` | exit `0`; versão igual ao pacote | saída `aif --version` + hash de `uv.lock` |
| AC-002 | `uv run pytest tests/integration/test_doctor.py::test_doctor_offline_never_invokes_provider -q` | JSON golden estável e provider fake não chamado | relatório pytest sanitizado |
| AC-003 | `uv run pytest tests/unit/test_config.py -q && uv run ruff check src tests && uv run pyright src tests` | config hostil rejeitada; lint e tipos aprovados | saídas dos gates |

## Fora de escopo

SPEC, SQLite operacional, worktrees, autenticação automática e smoke de provider real.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Nenhum transcript bruto ou segredo.
