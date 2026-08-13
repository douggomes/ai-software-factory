# Workspace de avaliação seguro

## Objetivo

A TASK-035 separa o worktree original da cópia que será consumida pelo runner
isolado. O adapter não executa código do repositório. Ele valida a identidade
persistida, captura o inventário Git e publica uma cópia privada, read-only e
content-addressed.

## Fluxo

1. confirme que `Workspace` corresponde exatamente a
   `factory_home/worktrees/<repo>/<run>/<task>` e que o lock exclusivo da mesma
   identidade continua materialmente retido pelo `WorkspaceManager`;
2. capture `HEAD` e listas limitadas de tracked, untracked, ignored e changed;
   os comandos Git usam um control dir privado criado a partir de `HEAD` e
   `index` abertos por descriptor, sem redescobrir `.git` pelo worktree; o
   `HEAD`, sua ref loose/packed e o índice originais são revalidados até a
   publicação, enquanto apenas o object database content-addressed é referenciado;
3. abra cada componente por descriptor com `O_NOFOLLOW`, escaneie e calcule
   SHA-256 antes de copiar;
4. não copie arquivos com conteúdo secreto ou nome de credencial; registre
   somente tipo, path e fingerprint;
5. verifique novamente todos os hashes e o estado Git;
6. publique o diretório por rename atômico, torne-o read-only e persista o
   manifest imutável no `ArtifactStore`;
7. revalide manifest, identidade e conteúdo antes de entregar a evidência no
   lifecycle `verified`; falha pós-publicação invalida e remove somente o root
   privado pertencente à captura.

Qualquer divergência de path, symlink, tipo, owner, limite, hash, lock ou estado
Git falha fechado. O erro não inclui conteúdo, segredo ou path externo.
Inventário limita arquivos, diretórios, profundidade e bytes agregados de paths;
evidência de segredo possui limites próprios de cardinalidade e tamanho.

O adapter recebe uma `WorkspaceLockCapability` explícita do composition root.
Ela empresta uma `WorkspaceLockLease` opaca, sem expor descriptor ou detalhe
POSIX, e confirma a mesma autoridade imediatamente antes da publicação do
manifest. Um lock file presente ou bloqueado por outra autoridade não substitui
essa capability; release/reacquire invalida a captura mesmo sem alterar inode
ou conteúdo.

## Evidência permitida

- run/task/base/HEAD e hashes de identidade;
- classificação, path relativo, tamanho, tipo binário e SHA-256;
- finding de segredo como `kind + path + fingerprint`;
- referência imutável ao manifest sanitizado.

Conteúdo de credencial, diff bruto, Git metadata, worktree original e paths do
host não entram no manifest. Outputs de subprocesso passam antes pelo
sanitizador streaming e somente artifacts limitados e redigidos atravessam a
porta.

O `AsyncioProcessRunner` de host rejeita sempre `UNTRUSTED`. Sua factory de
sanitização é uma dependência obrigatória ligada no composition root; nenhum
booleano declarativo pode transformar execução no host em isolamento.
Para comandos `TRUSTED`, o runner copia pelo descriptor os bytes do executável
autorizado para o runtime privado antes do spawn. Assim, troca concorrente do
pathname não muda o inode efetivamente executado; cwd também permanece preso a
descriptor, e falha/cancelamento encerra todo o process group mesmo após a
saída do líder.

A materialização possui limite público de 256 MiB em `ProcessPolicy`. Como o
pathname físico muda, executáveis recebem recursos exclusivamente por argv,
ambiente allowlisted ou cwd autorizado; descoberta relativa a `__file__`,
`$ORIGIN` ou `@executable_path` não faz parte do contrato do host runner.

## Diagnóstico

Execute somente os testes offline:

```bash
uv run pytest tests/contract/evaluation_workspace tests/security/test_evaluation_workspace.py -q
uv run pytest tests/integration/test_evaluation_workspace.py -q
uv run pytest tests/integration/test_process_output_sanitizer.py -q
```

Falha por mudança concorrente exige interromper a avaliação e iniciar nova
captura. Não reutilize snapshot parcial, não altere permissões manualmente e não
faça fallback para o worktree original.
