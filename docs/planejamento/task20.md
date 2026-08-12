---
title: "TASK-020 — Adapter Claude Code protegido"
task_id: TASK-020
release: "V0.3"
status: planned
depends_on: [TASK-018]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-020 — Adapter Claude Code protegido

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md), [security-review.md](security-review.md) e [ADR-0005](../adr/0005-cloud-only-model-runtime.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Claude Code fornece rota real independente para implement/review/repair sob permissões por papel.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- V0.2 aprovada na TASK-018.
- Baseline fixado no commit aprovado da TASK-018.
- Claude CLI disponível apenas para smoke opt-in; fixtures offline presentes.

## Arquivos permitidos

- `src/ai_software_factory/adapters/agents/claude_code.py`
- `src/ai_software_factory/adapters/agents/claude_normalizer.py`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `tests/contract/agents/claude/**`
- `tests/security/test_claude_policy.py`
- `docs/providers/claude-code.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ClaudeCodeWorker.execute(request) -> AsyncIterator[AgentEvent]` | `claude -p --output-format stream-json`; schema final quando requerido. |
| `ClaudeNormalizer.feed(line: bytes) -> tuple[AgentEvent, ...]` | Init/usage/tool/retry/failure normalizados. |
| `ClaudeRolePolicy` | reviewer read-only; implementer/repair somente worktree. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `api_key_guard` | bloqueia `ANTHROPIC_API_KEY` quando no_incremental_cost |
| `project_instructions` | dados não confiáveis; policy Factory vence |
| `external_directory` | deny |
| `provider_transport` | permitido somente ao Claude CLI em profile live explícito; web/tools continuam deny |
| `inference_mode` | cloud-only; endpoint local/self-hosted deny |
| `smoke` | opt-in |

## Passos de implementação

1. Implementar normalizador por fixtures stream/schema/retry.
2. Implementar worker e role permissions via ProcessRunner.
3. Aplicar billing/project-instruction/output boundaries.
4. Criar contract/security tests e guia de preflight.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Config local elevar tool/permission | Registrar config carregada e policy externa fail-closed | `test_project_instruction_cannot_escalate` |

## Critérios de aceite

- [ ] **AC-001** — Fixtures Claude passam AgentWorker contract incluindo retry sem duplicar attempt.
- [ ] **AC-002** — Reviewer não escreve; implementer não acessa externo; project injection não eleva tool/rede/Git.
- [ ] **AC-003** — API key incremental, endpoint local/self-hosted e output malformed/oversized falham antes de vazamento ou ação.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/contract/agents/claude -q` | contract suite completa | fixture/result matrix |
| AC-002 | `uv run pytest tests/security/test_claude_policy.py::test_project_instruction_cannot_escalate -q` | spies externos e Git zerados | permission audit |
| AC-003 | `uv run pytest tests/security/test_claude_policy.py::test_billing_and_output_boundaries -q` | rota não cloud bloqueada, erro tipado e artifacts sem canário | preflight + secret scan |

## Validação manual no terminal

1. `uv run pytest tests/contract/agents/claude -q`
   Esperado: Fixtures Claude passam pelo AgentWorker contract.
2. `uv run aif doctor --json`
   Esperado: Claude aparece sem expor API key, auth file ou configuração sensível.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-020` antes de publicar o draft PR.

## Fora de escopo

Agent SDK embutido, bare mode padrão, implementação do planner e roteamento por score.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
