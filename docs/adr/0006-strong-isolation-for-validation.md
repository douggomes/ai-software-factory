---
title: "ADR-0006 — Isolamento forte para validação de código não confiável"
status: Accepted
date: 2026-08-13
---

# ADR-0006 — Isolamento forte para validação de código não confiável

## Status

Accepted quando este ADR for integrado em `dev`. A integração humana deste PR
aprova a nova trust boundary; a implementação continua proibida até as
TASK-035 e TASK-036 serem formalmente ativadas, uma por vez, com baselines
posteriores às respectivas integrações.

## Contexto

`ProcessRunner` já executa argv sem shell, filtra ambiente, limita output e
encerra filhos. Esses controles reduzem risco, mas não isolam o host de código
executado por compile, lint, type-check ou testes. A TASK-008 classifica esses
comandos como `UNTRUSTED`, enquanto o composition root atual oferece apenas o
runner do host, que corretamente falha fechado. Logo, o profile publicável não
possui caminho de sucesso seguro.

Uma flag como `isolation_available=true` não constitui isolamento: ela é uma
asserção do chamador, não uma capability materializada. Também não basta montar
o worktree diretamente num container. Um writer concorrente poderia trocar o
conteúdo avaliado, comandos poderiam alterar o checkout original e Git/output
continuariam misturados à orquestração.

No macOS, Docker Desktop e Podman executam containers Linux dentro de uma VM.
Essa VM, combinada com os controles do runtime OCI, é a boundary aprovada para
o laboratório local. Processo filtrado no host, `sandbox-exec` ou um booleano
de capability não são equivalentes.

## Decisão

A implementação é dividida em duas fatias: TASK-035 entrega snapshot,
inspeção e sanitização sem executar código não confiável; TASK-036 materializa
o runner OCI e a imagem. A TASK-008 só é reativada após ambas.

### Porta e composição

- `ProcessRunner` continua sendo a porta consumida pelos gates.
- `AsyncioProcessRunner` é runner de host e rejeita sempre
  `TrustProfile.UNTRUSTED`; o campo declarativo `isolation_available` é
  removido do contrato.
- `OciIsolationRunner` é um adapter separado, ligado somente no composition
  root. Ele aceita execução não confiável apenas após um probe objetivo do
  runtime, da imagem e da policy.
- Backends iniciais são Docker Desktop e Podman machine locais. A escolha vem
  de configuração validada/registry; Core e Application não ramificam por nome
  de runtime.
- Runtime remoto, socket montado, modo privilegiado, host network, outro mount
  do host ou nested container são proibidos.

### Imagem e rede

- A imagem de validação é produzida pela Factory, possui definição versionada,
  SBOM e referência imutável `name@sha256:<64-hex>`.
- O runtime usa `--pull=never`; imagem ausente, tag mutável ou digest divergente
  falha antes de executar código.
- O build/provisionamento da imagem é uma operação separada, explícita e
  auditável. A execução de gates nunca constrói, baixa nem atualiza imagem.
- A rede do container é `none`. Proxy, credencial, agent socket, Docker/Podman
  socket e configuração do usuário não entram no processo ou no container.

### Filesystem e recursos

- Um `EvaluationWorkspace` cria snapshot privado do worktree autorizado, sem
  seguir symlinks, com manifest de paths/tipos/tamanhos/SHA-256 e limites
  fechados. Git metadata, credenciais e paths especiais não entram no snapshot.
- O container recebe somente esse snapshot. A raiz é read-only; diretórios
  temporários são `tmpfs`; a cópia de avaliação pode ser gravável e é
  descartada após captura das evidências.
- O worktree original nunca é montado no container. A identidade do snapshot e
  o manifest vinculam comandos, artifacts e aprovação ao mesmo conteúdo.
- O processo roda sem root, com `no-new-privileges`, todas as capabilities
  removidas, sem devices adicionais e com limites explícitos de PIDs, CPU,
  memória, output e tempo.
- Timeout, cancelamento ou overflow encerram o container e seus filhos; cleanup
  atua somente no identificador aleatório criado por aquela execução.

### Inspeção e evidência

- Captura de status/diff/ignored files sai da CLI e fica num adapter Git atrás
  de porta estreita. Path persistido no SQLite só é aceito após canonicalização
  contra `factory_home/worktrees/<repo>/<run>/<task>` e verificação sem symlink.
- A captura usa lock exclusivo da Factory e dupla verificação de identidade.
  Mudança concorrente antes, durante ou depois do snapshot invalida a avaliação.
- Todo arquivo alterado, inclusive ignored e binário, participa do inventário
  limitado. Conteúdo credencial ou secreto é lido somente pelo scanner local,
  nunca por argumento, log ou artifact; evidência contém tipo, path e
  fingerprint, não o valor.
- Um sanitizador canônico e streaming remove valores explícitos e padrões de
  private key, token cloud e credenciais antes de persistência. O adapter nunca
  devolve stdout/stderr bruto.

### Falha fechada

Runtime indisponível, daemon remoto, probe incompatível, imagem ausente,
policy incompleta, snapshot instável, limite excedido ou falha de sanitização
resulta erro de domínio e bloqueia o profile. Nenhum desses casos faz fallback
para execução no host.

## Consequências

### Positivas

- existe um caminho positivo material para os sete gates sem transformar o
  host runner em sandbox fictício;
- Docker e Podman podem substituir-se pelo mesmo contract suite;
- comandos avaliam uma cópia identificada, reduzindo TOCTOU e efeitos no
  worktree original;
- policy, inspeção Git e sanitização deixam a CLI e ganham testes próprios;
- ambiente sem runtime/imagem continua seguro por default.

### Negativas

- o desenvolvedor precisa provisionar runtime e imagem aprovados antes de usar
  o profile completo;
- build da imagem adiciona supply-chain, SBOM e manutenção de digest;
- Docker Desktop/Podman machine e seu hypervisor entram na trusted computing
  base local;
- a cópia do snapshot acrescenta I/O e espaço temporário limitados.

## Alternativas rejeitadas

- **Marcar gates como trusted:** executa código do repositório no host e viola o
  threat model.
- **Booleano `isolation_available`:** não prova nenhuma boundary e permite
  confused deputy.
- **Somente env allowlist/rlimit:** não impede acesso ao filesystem do host.
- **Worktree montado diretamente:** mantém TOCTOU e permite que testes alterem o
  checkout original.
- **Runtime OCI com tag/pull automático:** amplia rede e supply-chain durante o
  gate e quebra reprodutibilidade.
- **Backend único acoplado ao Docker:** viola DIP/OCP e exclui Podman sem motivo
  de domínio.

## Referências oficiais

- [Docker Desktop para Mac — permissões e Linux VM](https://docs.docker.com/desktop/setup/install/mac-permission-requirements/)
- [Docker run — controles de processo, recursos e segurança](https://docs.docker.com/reference/cli/docker/container/run/)
- [Docker network `none`](https://docs.docker.com/engine/network/drivers/none/)
- [Docker bind mounts read-only](https://docs.docker.com/engine/storage/bind-mounts/)
- [Podman machine — VM para macOS](https://docs.podman.io/en/latest/markdown/podman-machine.1.html)
- [Podman run — controles OCI](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
