---
title: "TASK-016 — Reviewer estruturado critério por critério"
task_id: TASK-016
release: "V0.2"
status: planned
depends_on: [TASK-015]
baseline_commit: "TO_BE_PINNED"
risk_level: high
---

# TASK-016 — Reviewer estruturado critério por critério

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Implementações aprovadas pelos gates recebem verdict semântico independente, estruturado e rastreável por AC.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-015 aprovada com Codex read-only.
- Baseline fixado no commit aprovado da TASK-015.
- SPEC v1 e ValidationSnapshot disponíveis.

## Arquivos permitidos

- `src/ai_software_factory/ports/review.py`
- `src/ai_software_factory/core/review_models.py`
- `src/ai_software_factory/application/reviewer.py`
- `schemas/review-result.v1.schema.json`
- `prompts/reviewer.v1.md`
- `tests/contract/review/**`
- `tests/integration/test_structured_review.py`
- `tests/security/test_review_prompt_injection.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `Reviewer.review(request: ReviewRequest) -> ReviewResult` | Todo AC vira pass/fail/unknown com reason e evidence refs. |
| `ReviewResult v1` | Verdict pass somente se todos os ACs passarem. |
| `ReviewRequest` | Task, ACs, diff, changed files e gates; sem transcript do implementer. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `unknown` | bloqueia pass |
| `evidence_path` | canonical dentro do worktree ou artifact existente |
| `raw_result` | sanitizado e imutável |
| `confidence` | informativo; nunca gate |
| `reviewer_context` | mínimo e separado de policy |

## Passos de implementação

1. Fechar schema/modelos e porta Reviewer.
2. Versionar prompt com delimitadores de dados não confiáveis.
3. Implementar service que valida cobertura/evidência/verdict.
4. Testar pass/fail/unknown, schema hostil, evidence externa e injection.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Reviewer obedecer instrução no diff | Policy separada, sandbox read-only e validação determinística | `test_diff_prompt_injection_cannot_pass_review` |

## Critérios de aceite

- [ ] **AC-001** — Todo AC aparece exatamente uma vez como pass/fail/unknown e verdict respeita a tabela.
- [ ] **AC-002** — Evidence inexistente/externa e output fora do schema são rejeitados, nunca tolerados.
- [ ] **AC-003** — Prompt injection no diff não altera policy nem produz pass sem evidência.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_structured_review.py::test_maps_every_acceptance_criterion -q` | cobertura total e verdict correto | ReviewResult v1 fixtures |
| AC-002 | `uv run pytest tests/integration/test_structured_review.py::test_rejects_invalid_schema_and_evidence -q` | InvalidStructuredOutput/Evidence | error artifacts sanitizados |
| AC-003 | `uv run pytest tests/security/test_review_prompt_injection.py -q` | resultado fail/unknown e zero tool escalation | security review snapshot |

## Validação manual no terminal

1. `uv run aif review <RUN-ID> --worker codex`
   Esperado: Produz ReviewResult v1 cobrindo todos os ACs com evidência.
2. `uv run pytest tests/security/test_review_prompt_injection.py -q`
   Esperado: Diff malicioso não altera policy nem obtém pass sem evidência.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-016` antes de publicar o draft PR.

## Fora de escopo

Repair automático, aprovação, confidence gate e acesso de escrita do reviewer.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
