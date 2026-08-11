# AI Software Factory

Factory local, assíncrona e auditável para orquestrar modelos de IA durante o desenvolvimento de software.

O repositório está em fase de bootstrap. A execução por agentes é governada por [AGENTS.md](AGENTS.md), e o backlog normativo está em [planejamento/plan.md](planejamento/plan.md).

Somente a task com `status: ready` pode ser executada. Use o validador antes de iniciar:

```bash
python3 scripts/validate_tasks.py
```

## Fluxo Git

- `main`: releases promovidas; nunca recebe implementação de task diretamente.
- `dev`: integração das tasks aprovadas.
- `task/TASK-NNN-descricao`: criada a partir de `dev` e publicada por pull request com destino a `dev`.
- promoção de release: pull request de `dev` para `main` após o gate formal.

Force-push em `main`/`dev` e push direto de task nessas branches são proibidos.
