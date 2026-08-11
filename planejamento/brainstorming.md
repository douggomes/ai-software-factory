---
title: Brainstorming de arquitetura da AI Software Factory
status: closed
date: 2026-08-11
target_release: "V1.1"
tags:
  - ai-software-factory
  - arquitetura
  - planejamento
---

# Brainstorming de arquitetura

## Objetivo

Transformar os guias Python V0.1 e V1.1 em um plano implementável, eliminando contradições, partes herdadas da versão .NET e decisões abstratas que impediriam uma execução incremental.

## Fontes lidas

- `AI-SOFTWARE-FACTORY-GUIA-IMPLEMENTACAO-v0.1-python.md`
- `AI-SOFTWARE-FACTORY-GUIA-IMPLEMENTACAO-v1.1-python.md`

Os dois arquivos foram lidos integralmente. O V0.1 é o contrato mínimo de confiabilidade; o V1.1 amplia o produto com reviewer, repair, context engineering, MCP, observabilidade, benchmark, roteamento e paralelismo.

## Diagnóstico do ambiente em 2026-08-11

| Item | Situação encontrada | Decisão de planejamento |
|---|---|---|
| macOS | 26.5.2, arm64, 16 GiB | Ambiente de desenvolvimento primário |
| Python | 3.14.6 | Desenvolver em 3.14 e manter compatibilidade mínima com 3.13 |
| uv | 0.11.33 | Gerenciador exclusivo de projeto, lockfile e execução |
| Git | 2.55.0 | Suficiente para worktrees e locks |
| Claude Code | 2.1.227 | Adapter entra após a V0.2 |
| Codex CLI | 0.147.0, autenticado via ChatGPT | Reviewer inicial e rota alternativa |
| OpenCode | 1.18.14 | Primeiro worker real |
| Ollama | não instalado | Não bloqueia a V0.1; entra apenas na V0.3 |
| Repositório | diretório vazio e ainda sem `.git` | Bootstrap é a primeira fatia de valor |

## Contradições encontradas e resolução

| Tema | Conflito nos guias | Resolução adotada |
|---|---|---|
| Estrutura do repositório | A edição Python ainda mostra projetos `.NET`, `.sln` e `Directory.Build.props` | Usar um monólito modular Python com layout `src/` |
| Observabilidade | O texto cita `System.Diagnostics` | Usar OpenTelemetry Python; traces e métricas primeiro, logs estruturados próprios |
| V0.1 | Um trecho exige failover; outro propõe primeiro sprint single-worker | O desenvolvimento pode passar por single-worker, mas a release V0.1 só existe após failover/continuação comprovados |
| Estado | Run e task aparecem como unidade durável em trechos diferentes | `Run` agrega a execução; `TaskExecution` é a unidade durável; `ExecutionAttempt` é descartável |
| Event journal | SQLite e NDJSON parecem duas fontes de verdade | SQLite é a fonte operacional transacional; NDJSON é evidência/export reconstruível |
| Configuração | Há exemplos JSON e YAML | `factory.toml` para configuração humana; JSON/JSONL para contratos e artifacts |
| Primeiro modelo | IDs de modelos são tratados como fixos | IDs ficam na configuração e são validados em `aif doctor`; nenhum modelo é constante de domínio |
| V1.1 | O documento define V1, mas não um corte preciso da V1.1 | V1.1 = roteamento explicável por evidência + paralelismo seguro por DAG + qualificação ampliada |

## Pesquisa externa que alterou o desenho

1. O `uv` mantém `pyproject.toml`, ambiente e `uv.lock` sincronizados; a CI deve usar `uv sync --locked` e `uv lock --check`. Fonte: [uv — locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/).
2. `codex exec` oferece sandbox explícito, JSONL e saída final validada por JSON Schema. O adapter usará `workspace-write`, nunca `danger-full-access` por padrão. Fonte: [OpenAI — non-interactive mode](https://developers.openai.com/codex/non-interactive-mode).
3. Claude Code oferece `json`, `stream-json`, `--json-schema` e eventos de retry. O adapter não dependerá apenas do exit code. Fonte: [Claude Code — programmatic usage](https://code.claude.com/docs/en/headless).
4. OpenCode tem defaults amplamente permissivos. A Factory criará um perfil explícito deny-by-default e negará diretórios externos, `.env`, commit e push. Fonte: [OpenCode — permissions](https://opencode.ai/docs/permissions/).
5. Os modelos do OpenCode Go mudam ao longo do tempo e devem ser descobertos/validados no preflight. Fonte: [OpenCode Go](https://opencode.ai/docs/go/).
6. O SDK Python atual do MCP suporta stdio e Streamable HTTP. A V0.4 começa somente com stdio. Fonte: [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/).
7. Em OpenTelemetry Python, traces e métricas estão estáveis, enquanto logs ainda estão em desenvolvimento. O plano mantém logs JSONL próprios. Fonte: [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/).
8. SQLite em WAL melhora a concorrência entre leitores e escritor, mas continua com apenas um escritor por vez. Escritas serão curtas, transacionais e com retry/busy timeout. Fonte: [SQLite WAL](https://sqlite.org/wal.html).
9. Uma `AsyncSession` do SQLAlchemy não pode ser compartilhada por tasks concorrentes. Cada operação terá sua própria sessão. Fonte: [SQLAlchemy — session concurrency](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks).
10. `asyncio.TaskGroup` oferece concorrência estruturada e propagação consistente de cancelamento. Será a base do scheduler da V1.1. Fonte: [Python 3.14 — TaskGroup](https://docs.python.org/3.14/library/asyncio-task.html#task-groups).

## Decisões arquiteturais fechadas

### D-001 — Monólito modular

Uma aplicação/CLI Python implantada localmente. Não haverá microserviços, fila, API web ou banco remoto até existir evidência de necessidade.

### D-002 — Portas e adapters

O Core conhece `Protocol`s e modelos normalizados. Git, SQLite, subprocessos e cada coding agent ficam atrás de adapters.

### D-003 — Hierarquia de execução

```text
Run
└── TaskExecution (durável, um worktree e um writer ativo)
    └── ExecutionAttempt (worker, retry, failover ou repair)
```

O schema já suportará várias tasks por Run, embora a V0.1 execute apenas uma.

### D-004 — Três fontes complementares

- intenção: SPEC versionada;
- estado operacional: SQLite;
- código em progresso: Git worktree;
- evidência volumosa: artifacts imutáveis em disco.

### D-005 — Failover não é repair

Failover troca um executor indisponível e preserva o trabalho. Repair corrige uma alteração que falhou em evidências de qualidade. Políticas, prompts, métricas e limites permanecem separados.

### D-006 — Segurança em camadas

Diretório do worktree, ambiente sanitizado, timeout, lista de argumentos sem shell, política do provider, lock de writer, gate de escopo, SecretGate e aprovação humana são controles complementares.

### D-007 — Roteamento explicável

Até a V1.0, seleção é ordenada e determinística. Na V1.1, scores podem usar métricas históricas, mas toda decisão precisa registrar candidatos, exclusões, pesos e justificativa. Uma LLM nunca será o router obrigatório.

### D-008 — Configuração e schemas

- `factory.toml`: perfis, workers, pools, timeouts e budgets;
- Pydantic: configuração e contratos persistidos;
- JSON Schema: saídas de planner/reviewer/repair;
- JSONL: eventos de providers e exports do journal.

### D-009 — Compatibilidade Python

`requires-python = ">=3.13,<3.15"` durante o ciclo da V1.1, com testes em 3.13 e 3.14. O teto deve ser revisto quando dependências suportarem oficialmente a próxima versão.

### D-010 — Laboratório separado

`factory-lab` será outro repositório, nunca um submódulo executado dentro da própria Factory. Fixtures Git descartáveis continuam dentro dos testes da Factory.

### D-011 — Release por evidência

Uma versão só é marcada quando seu cenário end-to-end e seus gates passam. Quantidade de componentes implementados não substitui o teste do comportamento prometido.

### D-012 — Sem merge autônomo na V1.1

Workers nunca fazem commit/push/merge. Mesmo após todos os gates, o fluxo termina em aprovação humana. A Factory pode criar o commit após aprovação, mas merge/push permanecem fora do escopo.

## Hipóteses não bloqueantes

- O primeiro projeto-laboratório será uma API Python simples de tickets.
- O primeiro worker real será OpenCode; Codex será o primeiro reviewer.
- O modo `no_incremental_cost` será padrão, mas configurável.
- Ausência de Ollama desabilita somente papéis locais; não falha o Core.
- Os caminhos do factory home e do laboratório serão configuráveis e nunca hardcoded para um usuário.

## Questões adiadas de forma consciente

Estas decisões não precisam de resposta antes da implementação porque serão tratadas como configuração ou experimento:

- qual modelo específico do OpenCode Go oferece melhor custo/qualidade;
- se Claude ou Codex é melhor reviewer;
- quais pesos usar no router dinâmico;
- quantas tasks paralelas o Mac suporta com estabilidade;
- se MCP melhora a taxa de sucesso.

## Critério de saída do brainstorming

- [x] Escopo da V0.1 e V1.1 definido.
- [x] Contradições Python/.NET removidas do desenho.
- [x] Unidade durável e fontes de verdade definidas.
- [x] Estratégia de segurança, custo e concorrência definida.
- [x] Lacunas restantes convertidas em configuração ou experimento mensurável.

Resultado: planejamento liberado para execução.
