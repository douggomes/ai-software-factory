---
title: "TASK-015 — Adapter Codex com sandbox explícito"
task_id: TASK-015
release: "V0.2"
status: planned
depends_on: [TASK-014]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-015 — Adapter Codex com sandbox explícito

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md), [security-review.md](security-review.md) e [ADR-0005](../adr/0005-cloud-only-model-runtime.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Codex torna-se runtime independente para review/implementação sob o mesmo AgentWorker contract.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- V0.1 aprovada na TASK-014.
- Baseline fixado no commit aprovado da TASK-014.
- Codex CLI disponível apenas para smoke opt-in; fixtures offline versionadas.

## Arquivos permitidos

- `src/ai_software_factory/adapters/agents/codex.py`
- `src/ai_software_factory/adapters/agents/codex_normalizer.py`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `tests/contract/agents/codex/**`
- `tests/security/test_codex_policy.py`
- `docs/providers/codex.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `CodexWorker.execute(request) -> AsyncIterator[AgentEvent]` | `codex exec --json`; sandbox por role via ProcessRunner. |
| `CodexNormalizer.feed(line: bytes) -> tuple[AgentEvent, ...]` | JSONL limitado; turn/error/failure normalizados. |
| `CodexRolePolicy` | reviewer=`read-only`; implementer/repair=`workspace-write`. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `reviewer_sandbox` | read-only |
| `implementer_sandbox` | workspace-write |
| `provider_transport` | permitido somente ao Codex CLI em profile live explícito; web/tools continuam deny |
| `inference_mode` | cloud-only; endpoint local/self-hosted deny |
| `auth` | sessão oficial existente; nunca copiar `auth.json` |
| `smoke` | opt-in |

## Passos de implementação

1. Implementar normalizador por fixtures success/error/partial.
2. Implementar worker/capabilities por role e schema option.
3. Aplicar policy de project instructions como dado não confiável.
4. Adicionar contract/security tests e guia de preflight.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Diff/project instruction instruir exfiltração | Sandbox mínimo, contexto delimitado e output não confiável | `test_injected_diff_cannot_change_sandbox` |

## Critérios de aceite

- [ ] **AC-001** — Fixtures Codex passam a contract suite sem tipo específico escapar ao Core.
- [ ] **AC-002** — Reviewer não escreve e project/diff injection não altera sandbox/rede/credenciais.
- [ ] **AC-003** — Preflight detecta auth sem copiar arquivo, rejeita endpoint local/self-hosted e limita output malformed/oversized.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/contract/agents/codex -q` | AgentWorker contract completo | fixture/result matrix |
| AC-002 | `uv run pytest tests/security/test_codex_policy.py::test_injected_diff_cannot_change_sandbox -q` | worktree/read-only e spies externos intactos | sandbox evidence |
| AC-003 | `uv run pytest tests/security/test_codex_policy.py::test_auth_and_output_boundaries -q` | nenhum auth artifact ou rota não cloud; erro tipado | preflight + artifact scan |

## Validação manual no terminal

1. `uv run pytest tests/contract/agents/codex -q`
   Esperado: Fixtures Codex passam pelo AgentWorker contract.
2. `uv run aif doctor --json`
   Esperado: Codex aparece com disponibilidade/auth detectada sem copiar auth.json.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-015` antes de publicar o draft PR.

## Fora de escopo

ReviewResult semântico, repair, aprovação e smoke obrigatório.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
