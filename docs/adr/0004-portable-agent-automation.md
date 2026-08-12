---
title: "ADR-0004 — Automação portátil entre agentes"
status: Accepted
date: 2026-08-11
---

# ADR-0004 — Automação portátil entre agentes

## Status

Accepted. Mudanças na fonte normativa, autoridade dos reviewers ou semântica fail-closed exigem novo ADR e task própria.

## Contexto

Claude Code e Codex possuem mecanismos equivalentes para instruções, skills, hooks e subagentes, mas usam paths e schemas de configuração distintos. Manter workflows completos em `.claude/` e `.codex/` criaria duas políticas sujeitas a drift justamente no controle de escopo e segurança.

## Decisão

- `AGENTS.md` permanece a única fonte de governança; `CLAUDE.md` usa o import nativo `@AGENTS.md`.
- Skills seguem Agent Skills e vivem em `.agents/skills/`. Claude usa symlink quando não há política adicional; `new-task` possui wrapper mínimo para desabilitar invocação implícita.
- Decisões de hook vivem em scripts Python stdlib. Configurações de host apenas selecionam evento, host e fase.
- Bloqueios `PreToolUse` usam exit code `2`, denominador comum dos hosts. Payload é limitado, validado e convertido antes da policy.
- Comandos de terminal são tokenizados e aceitos somente por allowlist fechada de executável, subcomando e argumentos; interpretadores livres, controle de shell e aliases absolutos falham fechados.
- Hook pós-edição audita escopo e executa Ruff sem auto-fix apenas no Python diretamente alterado.
- A auditoria de escopo parte do baseline imutável, reconhece separadamente o commit direto de ativação da task e continua enxergando mudanças já commitadas.
- Checklists de segurança e arquitetura são Markdown canônico. Manifestos Claude/Codex apenas impõem read-only, removem shell no Claude e apontam para o checklist.
- Nenhum skill ou reviewer fixa modelo; o host herda a seleção da sessão.

## Controles de segurança

- zero dependências adicionais e zero leitura de credenciais;
- paths canonicalizados sob a raiz e `.env*`/`auth.json` bloqueados antes da allowlist;
- shell composto, interpretador livre, path sensível, auto-fix e Git fora das operações normativas bloqueados por allowlist;
- diagnósticos limitados e sem ecoar payload, comando ou segredo;
- hooks são guardrails revisáveis, não substitutos de sandbox, gates e revisão humana.

## Consequências

- Alterar uma regra de workflow ou checklist exige uma mudança canônica, não duas.
- Cada host ainda precisa de um adaptador pequeno porque descoberta, metadata e sandbox não têm schema comum.
- O usuário precisa confiar no projeto e revisar os hooks em cada host antes da primeira execução.
- Ferramentas especializadas podem não atravessar hooks; os gates autoritativos continuam obrigatórios.

## Alternativas rejeitadas

- **Duplicar tudo em `.claude/` e `.codex/`**: rejeitado por drift e revisão duplicada.
- **Usar somente configuração Claude e importar no Codex**: rejeitado por depender de conversão local e não funcionar para novos clones de forma explícita.
- **Executar `ruff --fix` após edição**: rejeitado porque cria mutação oculta fora da intenção da tool call.
- **Fixar modelos nos reviewers**: rejeitado porque mistura papel com fornecedor/custo e quebra portabilidade.
