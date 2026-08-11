---
title: "TASK-NNN — Resultado observável"
task_id: TASK-NNN
release: "Vx.y"
status: planned
depends_on: [TASK-NNN]
baseline_commit: "TO_BE_PINNED"
risk_level: low | medium | high | critical
---

# TASK-NNN — Resultado observável

> [!important] Regra global de engenharia
> Esta task só pode ser executada se cumprir [engineering-standards.md](engineering-standards.md), [security-review.md](security-review.md), o [AGENTS.md](../AGENTS.md) e este contrato. O agente não pode ampliar o próprio escopo.

## Valor entregue

Descreva uma capacidade utilizável e demonstrável, não uma camada ou atividade interna isolada.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` estão aprovadas com evidência.
- [ ] `baseline_commit` contém o SHA imutável autorizado e corresponde ao checkout limpo.
- [ ] Entradas, ferramentas e fixtures das precondições existem.
- [ ] Nenhuma decisão obrigatória permanece aberta; defaults abaixo estão aprovados.
- [ ] Arquivos permitidos não conflitam com outra task ativa.

## Precondições

- Estado verificável necessário antes de qualquer edição.
- Comando read-only usado no preflight e resultado esperado.

## Arquivos permitidos

- `caminho/exato.py`
- `diretorio/limitado/**`

Qualquer outro path é proibido. Arquivo gerado só é permitido quando listado explicitamente.

## Arquivos proibidos

- `.env*`
- `planejamento/**`
- paths fora da raiz do repositório

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `Port.method(value: Type) -> Result` | Semântica, falhas, efeitos e compatibilidade esperados |

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `example.default` | Valor exato; mudança exige ADR/task |

Não use “conforme necessário”, “quando possível” ou escolha livre sem um default e condição objetiva.

## Passos de implementação

1. Menor mudança que produz contrato/teste executável.
2. Implementação pelas portas e fronteiras definidas.
3. Cenários negativos e de segurança.
4. Documentação/evidência.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Ameaça concreta | Mitigação objetiva | Nome/caminho do teste |

## Critérios de aceite

- [ ] **AC-001** — Resultado binário, observável e sem expressão subjetiva.
- [ ] **AC-002** — Cenário negativo ou de segurança falha de forma explícita.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/caminho/teste.py::test_caso -q` | Nome e resultado esperado | arquivo, snapshot ou saída sanitizada |
| AC-002 | `uv run pytest tests/caminho/teste.py::test_negativo -q` | Falha antes de efeito externo | arquivo, snapshot ou saída sanitizada |

Cada AC aparece uma única vez na matriz. O comando deve poder ser executado a partir da raiz e retornar `0` quando aprovado.

## Fora de escopo

Liste comportamentos parecidos que esta task deliberadamente não implementa.

## Evidência de conclusão

Liste os artifacts mínimos que permitem a outro agente reproduzir a decisão sem transcript ou conhecimento tácito.
