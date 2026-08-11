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

## Bootstrap e CLI

```bash
uv sync --locked
uv run aif --version
uv run aif doctor --json
```

`aif doctor --json` é totalmente offline: só verifica presença/versão de
Python, `uv`, Git, SQLite e das CLIs de worker/reviewer (`claude`, `codex`,
`opencode`) via `PATH`, sem nunca executá-las. Configuração vem de
`./factory.toml` (ver [factory.example.toml](factory.example.toml)); um
arquivo ausente usa defaults seguros e um arquivo com campo desconhecido ou
mal tipado falha antes de qualquer efeito.

## Gates locais

```bash
uv lock --check
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright src tests
uv run lint-imports
uv run pytest --cov=ai_software_factory --cov-branch
uv run pip-audit
uv build
```

Scan de segredos é ad hoc até uma task dedicada fixar baseline e CI:

```bash
uv run detect-secrets scan --all-files
```
