## Task

- ID: `TASK-NNN`
- Baseline `origin/dev`: `<40-char-sha>`
- Destino obrigatório: `dev`

## Valor entregue

Descreva o resultado observável desta task.

## Critérios e evidências

| AC | Comando | Resultado | Evidência |
|---|---|---|---|
| AC-001 | `comando exato` | pass/fail | artifact/link sanitizado |

## Gates globais

- [ ] Lock, lint, format, typing, architecture e testes passam.
- [ ] Dependency audit e secret scan passam.
- [ ] Diff respeita os arquivos permitidos.
- [ ] Clean Code, SOLID e threat model foram revisados.

## Segurança e riscos residuais

Liste os controles exercitados, findings e riscos residuais. Nunca inclua segredo, prompt bruto ou credencial.

## Regra de branch

- [ ] Este PR tem `base=dev`.
- [ ] Não há commit ou alteração direta em `main`.
