---
title: "TASK-036 — Runner OCI para gates não confiáveis"
task_id: TASK-036
release: "V0.1"
status: ready
depends_on: [TASK-035]
baseline_commit: "db7c306006010f6070707d7cb317cb2199253f30"
risk_level: critical
---

# TASK-036 — Runner OCI para gates não confiáveis

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md),
> [engineering-standards.md](engineering-standards.md),
> [security-review.md](security-review.md) e
> [ADR-0006](../adr/0006-strong-isolation-for-validation.md). O agente não pode
> ampliar paths, autoridade, rede, budget ou defaults.

## Valor entregue

A Factory executa argv `UNTRUSTED` somente sobre o snapshot da TASK-035, numa
boundary OCI local material e reproduzível. Docker Desktop e Podman machine
obedecem ao mesmo contrato; sem runtime/imagem aprovados, a execução bloqueia.

## Definition of Ready

- [x] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [x] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [x] Todas as precondições abaixo foram verificadas.
- [x] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [x] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-035 aprovada com snapshot, inspeção e sanitização contract-tested no merge
  `db7c306006010f6070707d7cb317cb2199253f30` de `origin/dev`.
- Docker Desktop ou Podman machine local pode ser usado no smoke opt-in; a suíte
  obrigatória usa runtime fake offline que captura argv/env/mounts.
- O baseline foi fixado no merge commit aprovado da TASK-035.
- Provisionamento da imagem é separado da execução; nenhum gate faz pull ou build implícito.
- Build explícito da imagem usa somente registries oficiais aprovados e produz digest, SBOM e provenance.

## Arquivos permitidos

- `src/ai_software_factory/core/process_models.py`
- `src/ai_software_factory/ports/processes.py`
- `src/ai_software_factory/adapters/process/asyncio_runner.py`
- `src/ai_software_factory/adapters/isolation/**`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `containers/validation/**`
- `tests/contract/processes/**`
- `tests/contract/isolation/**`
- `tests/integration/test_process_runner.py`
- `tests/integration/test_oci_isolation.py`
- `tests/integration/test_doctor.py`
- `tests/security/test_validation_isolation.py`
- `tests/unit/test_config.py`
- `docs/runbooks/validation-isolation.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado. Nenhuma
dependência Python nova é autorizada; a implementação usa stdlib e o runtime
OCI instalado separadamente.

## Arquivos proibidos

- `docs/planejamento/**`, `docs/adr/**`, `AGENTS.md`
- `.env*`, `**/auth.json`, keychain, tokens, chaves e credenciais
- socket Docker/Podman montado no container, `$HOME`, agent sockets ou runtime remoto
- worktree original ou path fora do snapshot privado da TASK-035
- paths fora da raiz ou alcançados por symlink
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ProcessRunner.run(ProcessRequest) -> ProcessResult` | Host runner rejeita sempre `UNTRUSTED`; OCI runner implementa a mesma porta e retorna somente refs sanitizadas. |
| `IsolationBackend.probe() -> IsolationCapability` | Prova runtime local, versão compatível, imagem por digest presente e policy suportada; não baixa nem executa repo. |
| `IsolationCapability` | Tipo opaco emitido pelo adapter, vinculado a backend/version/context/image digest/policy hash e validade curta. |
| `OciIsolationRunner.run(ProcessRequest) -> ProcessResult` | Implementa a porta com capability e snapshot authorizer injetados; executa argv literal somente no snapshot identificado. |
| `aif doctor` | Reporta disabled/available/incompatible e digest sanitizado; nunca faz pull, build ou probe live não solicitado. |

Adapters Docker e Podman são registrados no composition root e passam a mesma
contract suite. Core/Application não ramificam por backend e nenhum chamador
pode construir ou afirmar uma capability por booleano.

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `isolation.backend` | `disabled`; seleção explícita `docker` ou `podman` em config validada |
| `isolation.image` | obrigatório quando habilitado, sempre `name@sha256:<64-hex>` |
| `isolation.pull` | `never`; ausência da imagem falha fechado |
| `isolation.network` | `none` |
| `isolation.rootfs` | read-only; somente tmpfs e cópia privada do snapshot são graváveis |
| `isolation.privileges` | non-root, `no-new-privileges`, `cap-drop=ALL`, sem devices/socket |
| `isolation.resources` | 2 CPUs, 2 GiB, 256 PIDs, 900 s e 4 MiB por stream |
| `isolation.mounts` | somente snapshot privado em `/workspace`; worktree original e home são proibidos |
| `isolation.environment` | allowlist vazia + PATH/HOME/TMP internos controlados; zero proxy/token/agent |
| `isolation.runtime_context` | Docker `desktop-linux` ou Podman machine local; endpoint remoto é proibido |
| `untrusted_without_capability` | fail-closed, sem fallback ou reclassificação trusted |

O build versionado da imagem pode acessar apenas registries oficiais aprovados
durante provisionamento explícito. Esse acesso não é parte dos testes/gates nem
autoriza pull em runtime.

## Passos de implementação

1. Remover `isolation_available` declarativo e fechar modelos/porta de capability material.
2. Implementar registry e probes Docker/Podman por argv fixo, path canonicalizado e output limitado.
3. Implementar runner OCI com policy exata, container ID próprio, timeout/cancelamento e zero fallback.
4. Versionar Dockerfile, lock de digest, SBOM/proveniência e runbook de provisionamento separado.
5. Integrar configuração/doctor e cobrir contract, abuse tests e smoke OCI opt-in.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Booleano/fake capability libera host runner | capability opaca criada só pelo adapter após probe | `test_untrusted_never_falls_back_to_host_runner` |
| Container acessa host, rede ou credencial | argv fechado, snapshot único, network none, rootfs ro e env vazio | `test_oci_policy_has_no_host_network_socket_home_or_secret` |
| Tag muda ou gate baixa imagem | referência digest e pull never verificados antes do run | `test_mutable_or_missing_image_fails_without_pull` |
| Runtime remoto vira confused deputy | executable/context/connection locais allowlisted | `test_remote_runtime_and_unapproved_context_are_rejected` |
| Timeout deixa container/filhos | ID próprio, stop/kill limitado e verificação de ausência | `test_timeout_cancels_container_and_children` |

## Critérios de aceite

- [ ] **AC-001** — Host runner rejeita toda execução `UNTRUSTED`; runtime ausente/remoto/incompatível, imagem mutável/ausente ou policy incompleta falha antes de código e nunca faz fallback/pull.
- [ ] **AC-002** — Docker e Podman passam a mesma contract suite com rede none, rootfs read-only, non-root, capabilities zero, limites e somente snapshot privado montado.
- [ ] **AC-003** — Imagem versionada é reproduzível e registrada por digest, lock, SBOM e provenance; execução usa `pull=never` e não herda proxy, token, home ou socket.
- [ ] **AC-004** — Output/timeout/cancelamento obedecem ao contrato da TASK-035 e encerram container/filhos sem tocar worktree original ou deixar artifact bruto.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/security/test_validation_isolation.py::test_untrusted_never_falls_back_to_host_runner -q` | spies provam zero spawn/pull fora da capability | erro de domínio sanitizado + probe record |
| AC-002 | `uv run pytest tests/contract/isolation -q` | mesma suite valida Docker e Podman com argv/env exatos | capability/policy snapshot sem host paths |
| AC-003 | `uv run pytest tests/integration/test_oci_isolation.py::test_image_digest_sbom_and_offline_execution -q` | lock/digest/provenance conferem e runtime recebe pull never | image manifest + SBOM sanitizada |
| AC-004 | `uv run pytest tests/integration/test_oci_isolation.py::test_output_timeout_and_cancellation_are_bounded -q` | canários ausentes; runtime e filhos terminados | ProcessResult/artifact refs sanitizados |

## Validação manual no terminal

1. `uv run pytest tests/contract/isolation tests/security/test_validation_isolation.py -q`
   Esperado: os dois backends obedecem à policy fechada e escapes falham antes de execução não autorizada.
2. `uv run aif doctor`
   Esperado: reporta isolamento como disabled/available/incompatible e imagem por digest, sem pull, build, rede ou exposição de configuração sensível.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-036`
antes de publicar o draft PR.

## Fora de escopo

Kubernetes, runtime remoto, microVM própria, execução privilegiada, nested
containers, network allowlist para testes, provisionamento automático no gate,
multi-tenant e suporte a host sem VM/container aprovado.

## Evidência de conclusão

Contract/security reports, lock de imagem, SBOM, provenance, runbook e relatório
obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com
comando/resultado/evidência, gates globais, revisão canônica e riscos residuais.
Após os gates, o agente cria commit, publica a branch e abre/atualiza
automaticamente um draft PR para `dev` usando `gh`. Nenhum output bruto, host
path, segredo ou socket entra na evidência.
