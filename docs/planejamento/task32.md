---
title: "TASK-032 — Automação agnóstica de agentes"
task_id: TASK-032
release: "V0.1"
status: done
depends_on: [TASK-007]
baseline_commit: "6a0d60db0e4808a49feb1c366ab0db6bbb4eaff8"
risk_level: critical
---

# TASK-032 — Automação agnóstica de agentes

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Claude Code e Codex executam o mesmo workflow normativo, aplicam a mesma política de escopo e usam reviewers equivalentes sem duplicar regras de negócio entre hosts.

## Definition of Ready

- [x] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [x] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo de código.
- [x] Todas as precondições abaixo foram verificadas.
- [x] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [x] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-007 aprovada e integrada no commit `b94cc61913bfad0da6804c526fa4e574feed35c0`.
- Commit de governança `6a0d60db0e4808a49feb1c366ab0db6bbb4eaff8` reconciliou TASK-005–008.
- Python, `uv`, `git`, Claude Code e Codex permanecem ferramentas do host; scripts compartilhados usam apenas a biblioteca padrão.
- Configurações locais de hooks só entram em vigor após o usuário confiar no repositório e revisar os hooks no respectivo host.

## Arquivos permitidos

- `AGENTS.md`
- `CLAUDE.md`
- `.agents/skills/**`
- `.agents/reviewers/**`
- `.claude/settings.json`
- `.claude/skills/**`
- `.claude/agents/**`
- `.codex/hooks.json`
- `.codex/agents/**`
- `scripts/agent_automation/**`
- `tests/automation/**`
- `docs/adr/0004-portable-agent-automation.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `run-task/SKILL.md` | Orquestra o ciclo normativo referenciando fontes existentes; não duplica regras nem escolhe modelo. |
| `new-task/SKILL.md` | Somente por solicitação explícita; cria contrato `planned` com `TO_BE_PINNED` e nunca ativa a própria task. |
| `hook.py --host HOST --phase PHASE` | Normaliza payload Claude/Codex, bloqueia escrita fora do escopo e executa checks sem auto-fix. |
| reviewers compartilhados | Checklists canônicos read-only; manifestos de host apenas selecionam formato e restrições. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `instructions_source` | `AGENTS.md`; Claude importa por `CLAUDE.md` |
| `skills_source` | `.agents/skills`; adaptador Claude referencia a fonte canônica |
| `hook_policy_source` | `scripts/agent_automation` usando somente stdlib |
| `policy_failure` | fail-closed, exit code `2`, mensagem sanitizada |
| `post_edit` | Ruff check/format check no arquivo Python; auto-fix proibido |
| `reviewer_authority` | read-only, sem commit/push/rede incremental |
| `reviewer_model` | herdado do host; nenhum modelo fixado |

## Passos de implementação

1. Criar skills portáveis e a ponte `CLAUDE.md` → `AGENTS.md`.
2. Implementar normalização de payload, policy de escopo e checks pós-edição.
3. Criar adaptadores de hooks e reviewers read-only para os dois hosts.
4. Testar descoberta, equivalência, fail-closed, traversal, payload hostil e ausência de auto-fix.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Configuração específica divergir ou ampliar autoridade | fonte canônica + adaptadores finos + validação estrutural | `test_host_adapters_cannot_override_canonical_policy` |
| Hook ser contornado por path/payload hostil | canonicalização, limite de input, bloqueio de shell mutável e fail-closed | `test_scope_hook_denies_escape_secret_and_mutating_shell` |
| Reviewer alterar o repositório | sandbox/tools read-only e instrução compartilhada | `test_reviewers_are_model_agnostic_and_read_only` |

## Critérios de aceite

- [x] **AC-001** — Claude e Codex carregam `AGENTS.md` e as mesmas skills canônicas sem duplicação do workflow.
- [x] **AC-002** — Payloads equivalentes dos dois hosts produzem a mesma decisão; escape, segredo e shell mutável falham fechados.
- [x] **AC-003** — Reviewers de segurança e arquitetura usam o mesmo checklist, herdam o modelo e não possuem autoridade de escrita.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/automation/test_portable_skills.py::test_both_hosts_reference_canonical_skills -q` | instruções e skills resolvem para fonte única | paths e hashes canônicos |
| AC-002 | `uv run pytest tests/automation/test_agent_hooks.py::test_scope_hook_denies_escape_secret_and_mutating_shell -q` | matriz Claude/Codex retorna exit 2 | decisões sanitizadas |
| AC-003 | `uv run pytest tests/automation/test_reviewers.py::test_reviewers_are_model_agnostic_and_read_only -q` | sem modelo fixo nem tools de escrita | manifestos validados |

## Validação manual no terminal

1. `python3 scripts/agent_automation/validate_setup.py`
   Esperado: Exibe `PASS` para instruções, duas skills, dois hooks e dois reviewers em Claude e Codex.
2. `python3 scripts/agent_automation/hook.py --self-test`
   Esperado: Exibe decisões equivalentes de allow/deny para os payloads internos sem escrever arquivos.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-032` antes de publicar o draft PR.

## Fora de escopo

Instalação global de plugins, escolha de modelo, CI remoto, auto-merge e concessão de novas permissões aos agentes.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
