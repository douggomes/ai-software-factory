---
title: "TASK-008 — Gates determinísticos e snapshots"
task_id: TASK-008
release: "V0.1"
status: done
depends_on: [TASK-036]
baseline_commit: "d1d5109701856ee1c0073da91e166805f868bc66"
risk_level: high
---

# TASK-008 — Gates determinísticos e snapshots

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade ou defaults.

## Valor entregue

Toda alteração recebe avaliação reproduzível de scope, diff, comandos e segredos sem consultar LLM.

## Definition of Ready

- [x] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [x] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [x] Todas as precondições abaixo foram verificadas.
- [x] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [x] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-036 aprovada; ela herda da TASK-035 snapshot seguro, inspeção Git e sanitização validados.
- Baseline será fixado no merge commit aprovado da TASK-036 em `origin/dev`.
- SPEC v1 fornece allowed scope e comandos como argv.
- Runtime e imagem de validação aprovados estão disponíveis; ausência falha fechado sem fallback no host.

## Arquivos permitidos

- `src/ai_software_factory/ports/validation.py`
- `src/ai_software_factory/evaluation/models.py`
- `src/ai_software_factory/evaluation/gates.py`
- `src/ai_software_factory/evaluation/runner.py`
- `src/ai_software_factory/cli.py`
- `tests/contract/validation/**`
- `tests/integration/test_validation_gates.py`

Qualquer outro path é proibido, inclusive arquivo gerado não listado.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ValidationGate.evaluate(context: GateContext) -> GateResult` | Resultado imutável com status, findings e artifact refs. |
| `Evaluator.run(profile: ValidationProfile) -> ValidationSnapshot` | Ordem estável; executa todos os gates obrigatórios aplicáveis. |
| `aif validate RUN-ID --profile NAME` | Somente profile registrado; nunca comando ad hoc. |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `gate_order` | scope,diff,secrets,compile,lint,types,tests |
| `required_failure` | bloqueia pipeline |
| `secret_evidence` | tipo+path+fingerprint; valor proibido |
| `snapshot_overwrite` | false |
| `profile_source` | SPEC/config validada |
| `command_trust` | `UNTRUSTED`; execução somente pelo `OciIsolationRunner` aprovado |
| `isolation_missing` | bloqueia profile; nunca reclassifica comando como trusted |

## Passos de implementação

1. Definir porta/modelos e profiles fechados.
2. Implementar ScopeGate, DiffGate, SecretGate e CommandGate.
3. Persistir snapshots e stdout/stderr somente por ArtifactStore.
4. Testar pass/fail/timeout/scope/secret e repetição sem overwrite.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Gate aceitar mudança perigosa ou vazar segredo | Fail-closed, escopo independente e fingerprint | `test_scope_secret_and_diff_fail_closed` |
| Profile executar repo no host | capability OCI da TASK-036 e nenhuma reclassificação trusted | `test_registered_profile_requires_strong_isolation` |

## Critérios de aceite

- [ ] **AC-001** — Mudança fora de scope, segredo ou `git diff --check` falho bloqueiam snapshot.
- [ ] **AC-002** — Profile registrado executa os sete gates na ordem, sobre o mesmo snapshot, via isolamento forte; argv/cwd/env e evidências permanecem validados e sanitizados.
- [ ] **AC-003** — Reexecução cria snapshot novo e resultado obrigatório falho impede sucesso.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/integration/test_validation_gates.py::test_scope_secret_and_diff_fail_closed -q` | três casos bloqueados | snapshots de findings |
| AC-002 | `uv run pytest tests/integration/test_validation_gates.py::test_registered_profile_runs_all_gates_with_strong_isolation -q` | sete gates usam snapshot/capability e ausência de isolamento bloqueia | ProcessResult refs + snapshot/capability hashes |
| AC-003 | `uv run pytest tests/integration/test_validation_gates.py::test_snapshots_are_immutable_and_mandatory -q` | IDs distintos; state não avança | ledger + artifact hashes |

## Validação manual no terminal

1. `uv run aif validate <RUN-ID> --profile tests`
   Esperado: Produz novo ValidationSnapshot e código 0 apenas quando todos os gates obrigatórios passam.
2. `uv run aif validate <RUN-ID> --profile tests`
   Esperado: Uma segunda execução cria snapshot distinto sem sobrescrever a primeira.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-008` antes de publicar o draft PR.

## Fora de escopo

Review semântico, hidden tests e criação dinâmica de comandos.

## Evidência de conclusão

Relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança, saída da validação manual e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum transcript bruto ou segredo.
