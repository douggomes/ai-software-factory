---
title: "ADR-0003 — Worktree Git isolado por task"
status: Accepted
date: 2026-08-11
---

# ADR-0003 — Worktree Git isolado por task

## Status

Accepted. A decisão é aplicada pela porta `WorkspaceManager` e pelo adapter
`GitWorktreeManager`. Revisões de autoridade, raiz de filesystem ou política
de cleanup exigem novo ADR e nova task.

## Contexto

Workers de tasks distintas precisam editar o mesmo repositório sem alterar o
checkout principal nem disputar silenciosamente o mesmo diretório. O host
também não pode executar hooks Git arbitrários durante a preparação, e o
cleanup não pode transformar um path externo ou um symlink em alvo de remoção.

## Decisão

Cada identidade `(repository, run_id, task_id, base_commit)` recebe um
worktree em:

```text
<factory_home>/worktrees/<repo>/<run>/<task>
```

O adapter calcula a identidade a partir de paths canonicalizados, valida que
o commit-base é um SHA-1 commit existente e cria a branch determinística
`aif/<run>/<task>`. Um lock POSIX exclusivo e não bloqueante em
`<factory_home>/locks/<repo>/<run>/<task>.lock` permite no máximo um writer por
task. A reentrada é permitida somente quando branch, HEAD, path e base
continuam exatamente compatíveis.

Todo Git controlado usa argumentos separados, `--` nos caminhos e
`-c core.hooksPath=/dev/null`. O adapter não faz fetch, push ou qualquer outra
operação de rede. `inspect` somente lê status/diff; `clean` exige confirmação
explícita, lock mantido pelo próprio manager e revalidação de identidade antes
de chamar `git worktree remove --force`.

## Controles de segurança

- `factory_home`, worktree, lock e repository são absolutos e rejeitam
  symlinks nos componentes observados;
- raízes de worktree e lock são verificadas contra `factory_home` antes de
  qualquer comando ou cleanup;
- diretórios de runtime usam `0700` e locks usam `0600`;
- o lock é adquirido antes da validação/criação e liberado em falhas da
  tentativa que o adquiriu;
- paths que aparecem ou mudam para symlink, traversal ou identidade
  incompatível falham fechado e não são removidos;
- a CLI de inspeção limita a descoberta local, usa Git absoluto, ambiente
  mínimo, timeout e nunca shell.

## Consequências

- O checkout principal permanece no commit original enquanto cada task usa
  uma árvore isolada e inspecionável.
- Retomadas podem reutilizar um worktree compatível, mas não podem reutilizar
  um worktree que tenha avançado de base ou mudado de branch.
- Worktrees órfãos permanecem após falha por default; cleanup automático não é
  permitido sem confirmação externa e autoridade do manager.
- O lock é POSIX e a implementação atual é destinada ao laboratório local
  mono-tenant da V1.1; suporte multiplataforma ou multi-host exige decisão
  separada.

## Alternativas rejeitadas

- **Editar diretamente o checkout principal**: rejeitado porque mistura tasks,
  impede retomada determinística e expõe a branch de integração.
- **Copiar o repositório com filesystem copy**: rejeitado porque perde a
  semântica nativa de branches/worktrees e torna a identidade Git mais difícil
  de verificar.
- **Permitir cleanup por path recebido da CLI**: rejeitado por traversal,
  symlink/TOCTOU e confused deputy; a remoção depende do objeto `Workspace`
  validado e do lock do manager.
