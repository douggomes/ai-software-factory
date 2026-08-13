# Isolamento OCI de validação

## Objetivo

Comandos classificados como `UNTRUSTED` não executam no host. O host runner
rejeita esses requests; somente o adapter OCI pode avaliá-los, após provar o
runtime local, o contexto de VM e a imagem por digest.

## Provisionamento explícito

1. Revise `containers/validation/Dockerfile`, `image.lock.json`, `sbom.cdx.json`
   e `provenance.json`.
2. Faça o build e a carga da imagem em uma ação humana separada e registre o
   digest produzido. Não habilite uma tag mutável.
3. Configure `factory.toml` com `isolation.backend = "docker"` ou `"podman"`
   e uma referência `name@sha256:<64-hex>` aprovada.
4. Execute `aif doctor --json`. Ele apenas informa `disabled`, `available` ou
   `incompatible`; não faz pull, build ou chamada de rede.

## Política do runtime

- `--pull=never`, rede `none`, rootfs read-only e tmpfs controlado;
- usuário `65532:65532`, `no-new-privileges` e `cap-drop=ALL`;
- máximo de 2 CPUs, 2 GiB, 256 PIDs, 900 segundos e 4 MiB por stream;
- somente o snapshot privado verificado é montado em `/workspace` como leitura;
- home, worktree original, sockets, proxy, token e devices não são montados;
- timeout ou cancelamento removem somente o container de nome aleatório da
  própria execução.

Ausência de runtime, contexto remoto, imagem não presente, digest divergente,
snapshot não autorizado ou falha no cleanup bloqueia a validação sem fallback
para o host.
