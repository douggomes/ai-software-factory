---
title: "ADR-0001 — Workers são CLIs de coding agent, não chamadas diretas a provider APIs"
status: Accepted
date: 2026-08-11
---

# ADR-0001 — Workers são CLIs de coding agent, não chamadas diretas a provider APIs

## Status

Accepted. ADRs são imutáveis após aceitos; qualquer revisão cria um novo ADR
que substitui este, conforme [docs/adr/README.md](README.md).

## Contexto

A Factory precisa executar um `AgentWorker` (ver [plan.md](../../planejamento/plan.md#11-contratos-públicos-principais))
que edita um worktree real até satisfazer os critérios de aceite de uma task.
Duas famílias de integração foram consideradas:

1. Chamar diretamente a API de completions/mensagens de um provider (por
   exemplo a Anthropic Messages API ou a OpenAI API) e implementar dentro da
   Factory o loop agentic: planejamento, tool use, aplicação de diffs,
   sandboxing de execução de código e parsing de streaming.
2. Invocar CLIs de coding agent já existentes — OpenCode, Codex CLI e Claude
   Code — que já implementam esse loop, e normalizar sua saída para o
   `AgentWorker` port.

O plano adota a segunda opção para V0.1–V1.1 (`plan.md`, seção 4 e tabela de
contratos; `brainstorming.md`, decisões D-001/D-002).

## Decisão

Workers e o reviewer inicial são sempre CLIs de coding agent invocadas como
subprocesso sem shell (`ProcessRunner`, `shell=False`, argumentos array), nunca
chamadas HTTP diretas a uma API de provider a partir do Core ou da
Application. Cada adapter (`adapters/agents/*`) traduz o formato específico de
saída de sua CLI — JSONL/`--json-schema` no Codex, `stream-json` no Claude
Code, output do OpenCode — para os eventos normalizados definidos pela porta
`AgentWorker`, sem ramificação por nome de provider fora do adapter.

## Consequências

- A Factory não reimplementa o loop de tool-use, aplicação de diffs e
  sandboxing de execução de código: cada CLI já resolve isso, e a Factory
  soma controles próprios (worktree isolado, `env` allowlist, permissões
  deny-by-default, `--sandbox workspace-write` no Codex, perfil explícito no
  OpenCode) por cima, sem duplicar essa responsabilidade no Core.
- Autenticação usa o mecanismo nativo de cada CLI (login/assinatura do Claude
  Code, autenticação via ChatGPT no Codex, credenciais do OpenCode), em vez de
  chaves de API cobradas por token geridas pela Factory. Isso é consistente
  com o default `no_incremental_cost = true` (`plan.md`, seção 15;
  `factory.example.toml`) e evita que a Factory acumule ou logue segredos de
  billing.
- A Factory passa a depender da estabilidade do contrato de linha de comando
  (flags, formato de saída, exit codes) em vez de um contrato HTTP versionado.
  Mudança de formato de CLI é um risco aceito e mitigado por contract
  fixtures versionadas, capability discovery e falha explícita em
  versão/capability incompatível (`plan.md`, seção 19, risco "Formatos de CLI
  mudarem"; `engineering-standards.md`, seção 4).
- Cada CLI trata seu próprio provider como implementação interna; o Core
  nunca interpreta texto específico de provider nem decide por nome de
  provider (`engineering-standards.md`, seção 2, regra OCP/DIP).

## Alternativas rejeitadas

- **Chamar a API de completions/mensagens diretamente**: rejeitada para
  V1.1 porque exigiria reimplementar tool-use loop, aplicação de patch e
  sandboxing de execução de código dentro da Factory, ampliando a superfície
  de autoridade do Core e afastando o desenho de "menor privilégio" do
  [threat model](../../planejamento/security-review.md). Pode ser revisitada
  se a instabilidade de contrato de CLI se tornar limitante, mas exigiria um
  novo ADR e uma nova revisão de threat model, não uma escolha local do
  agente.
