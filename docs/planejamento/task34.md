---
title: "TASK-034 — Bootstrap de governança para projetos greenfield"
task_id: TASK-034
release: "V0.5"
status: planned
depends_on: [TASK-033]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-034 — Bootstrap de governança para projetos greenfield

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade, rede, budget ou defaults.

## Valor entregue

Antes de gerar código em um projeto vazio, a Factory cria e valida um pacote de governança agnóstico de agente: `AGENTS.md`, normas de engenharia, segurança, testes, arquitetura, operação e FinOps adequadas ao tipo de produto. Perfis backend, frontend, mobile e infraestrutura transformam Clean Code, SOLID, qualidade, acessibilidade, custo e segurança em regras e gates verificáveis.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-033 está aprovada e fornece evidências versionadas das baselines oficiais selecionadas.
- O alvo foi classificado como greenfield por uma política determinística e seu path canônico pertence à raiz autorizada.
- Tipo de workload, plataformas, classificação de dados, criticidade, região e perfil de custo são entradas estruturadas; ausência ou ambiguidade bloqueia `apply`.
- Preview é offline; atualização de documentação ocorre somente pela capacidade e pelo perfil aprovados na TASK-033.
- Um projeto com `AGENTS.md`, regras, código ou histórico preexistente não é greenfield e entra no fluxo de reconciliação, fora do escopo desta task.

## Arquivos permitidos

- `src/ai_software_factory/core/governance_models.py`
- `src/ai_software_factory/ports/governance.py`
- `src/ai_software_factory/application/project_bootstrap.py`
- `src/ai_software_factory/adapters/governance/**`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `templates/governance/**`
- `schemas/governance-manifest.v1.json`
- `tests/contract/governance/**`
- `tests/integration/test_greenfield_governance.py`
- `tests/security/test_greenfield_governance.py`
- `docs/runbooks/greenfield-governance.md`
- `docs/adr/0010-greenfield-governance-bootstrap.md`

Qualquer outro path é proibido, inclusive arquivo gerado não listado. Os testes criam os projetos alvo exclusivamente em diretórios temporários canônicos.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, keychain, tokens, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- regras, código ou configuração de projeto real preexistente
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `ProjectGovernanceBootstrap.preview(request: GovernanceBootstrapRequest) -> GovernancePlan` | Classifica o alvo, compõe profiles, resolve evidências e produz diff/hash sem escrita. |
| `ProjectGovernanceBootstrap.apply(plan: GovernancePlan, authorization: WriteAuthorization) -> GovernanceManifest` | Revalida alvo/plano/autoridade e publica o pacote de forma transacional, com manifest final e sem overwrite. |
| `GovernanceProfile.compose(base, workload, risk) -> GovernanceRules` | Composição determinística e monotônica: profile especializado pode restringir, nunca remover regra baseline. |
| `GovernanceValidator.validate(root: Path) -> GovernanceValidation` | Confirma arquivos, versões, hashes, seções e gates mínimos antes de liberar geração de código. |
| `GovernanceManifest v1` | Target hash, template/profile versions, evidence refs, arquivos/hashes, policy hash e estado do implementation gate. |
| `aif project governance preview|apply|validate` | `preview` é default sem efeitos; `apply` exige autorização explícita vinculada ao plan hash; `validate` é read-only. |

O `AGENTS.md` gerado é a fonte normativa única do projeto e é agnóstico de Claude, Codex e OpenCode. Arquivos específicos de host podem apenas importar ou apontar para essa fonte; nunca duplicam ou enfraquecem regras.

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `governance.mode` | `preview`; escrita somente por `apply` com `WriteAuthorization` |
| `governance.target` | diretório vazio, sem symlink, Git ausente ou sem commit/código/configuração |
| `governance.overwrite` | `false`; qualquer colisão aborta todo o pacote |
| `governance.template_version` | `v1`, registrada com hash |
| `governance.profile_order` | `baseline` → exatamente um workload → zero ou mais overlays compatíveis → `risk`; merge só adiciona/restringe |
| `governance.workloads` | `backend-python`, `frontend-web`, `mobile` ou `infra-only` |
| `governance.overlays` | mobile exige exatamente um de `ios`, `android`, `flutter` ou `react-native`; `infra-cloud` é opcional nos workloads de aplicação |
| `governance.output` | `AGENTS.md` + `docs/engineering-standards.md` + `docs/security/threat-model.md` + `docs/architecture/adr/README.md` + `docs/testing/quality-gates.md` + `docs/operations/reliability.md` + `docs/finops/cost-policy.md` + `.aif/governance-manifest.json` |
| `quality.coverage` | branch coverage mínimo 85%, 100% para invariantes críticas e nenhum decréscimo sem ADR/aprovação |
| `quality.architecture` | SOLID, Clean Code, dependências por portas, typing estrito e gates por stack |
| `data.database` | conexão/pool gerenciado; proibido abrir conexão ou executar consulta individual dentro de loop; N+1, transação longa e scan sem limite falham no gate |
| `finops` | budget/tag/owner por recurso, custo unitário e forecast antes do launch; alertas, quotas, retenção e custo de DB/rede/storage/IA obrigatórios |
| `infrastructure` | IaC versionada, least privilege, encryption, backup/restore, SLO, observabilidade, rollback e limites de recurso |
| `frontend` | typing estrito, WCAG 2.2 AA, HTML semântico, keyboard/focus, segurança XSS/CSP, component/E2E tests e Core Web Vitals pinados por evidência oficial |
| `mobile` | lifecycle/state restoration, acessibilidade, permissionamento mínimo, storage seguro, offline/sync, bateria/memória/rede, matriz OS/device e privacidade de loja |
| `implementation_gate` | `blocked` até `GovernanceValidator` aprovar manifest e todos os arquivos |

O profile usa valores atuais somente quando acompanhados da evidência da TASK-033; versão, hash, URL e data ficam pinados no manifest. Mudança de baseline oficial não reescreve silenciosamente projeto existente.

## Passos de implementação

1. Fechar modelos, schema v1, profiles monotônicos e templates agnósticos de host.
2. Implementar preview determinístico e validator sem efeitos.
3. Implementar publicação create-exclusive/transacional com staging, journal, rollback, manifest final e revalidação de path, plano e autorização.
4. Integrar o implementation gate antes de qualquer etapa que gere código.
5. Cobrir todos os workloads, abuso de filesystem, completude das regras e documentação do fluxo greenfield.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| Factory sobrescreve regras do usuário | greenfield estrito, `overwrite=false` e create-exclusive | `test_existing_rules_abort_without_partial_write` |
| Profile especializado enfraquece baseline | merge monotônico validado por regra/ID | `test_profile_cannot_remove_baseline_rule` |
| Path traversal/symlink/TOCTOU escreve fora do alvo | canonicalização, caminhada sem seguir symlink e revalidação no apply | `test_symlink_swap_and_traversal_fail_closed` |
| Template omite segurança, custo ou qualidade | schema e catálogo mínimo por workload | `test_every_profile_contains_required_rule_catalog` |
| Regras oficiais ficam obsoletas sem rastreabilidade | evidence refs pinadas e atualização explícita | `test_manifest_pins_documentation_evidence` |
| Escrita parcial deixa projeto governado pela metade | staging, journal, fsync/rename por arquivo, manifest final e rollback seguro | `test_write_failure_leaves_no_partial_pack` |

## Critérios de aceite

- [ ] **AC-001** — Cada workload suportado gera em preview o mesmo `GovernanceManifest v1` e pacote byte a byte estável para entradas/evidências equivalentes.
- [ ] **AC-002** — Todo pacote contém regras verificáveis de Clean Code/SOLID, testes/cobertura, segurança/supply chain, FinOps, infraestrutura, banco e os controles específicos de frontend ou mobile aplicáveis.
- [ ] **AC-003** — Alvo não vazio, regra preexistente, profile desconhecido, colisão, traversal, symlink/TOCTOU ou falha de escrita aborta sem overwrite nem pacote parcial.
- [ ] **AC-004** — O pipeline impede geração de código até validar manifest, hashes, evidências e catálogo mínimo; mudança posterior invalida o gate.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/contract/governance tests/integration/test_greenfield_governance.py::test_supported_profiles_are_deterministic -q` | profiles repetidos geram mesmos arquivos/hashes | golden manifests por workload |
| AC-002 | `uv run pytest tests/integration/test_greenfield_governance.py::test_every_profile_contains_required_rule_catalog -q` | catálogo baseline e overlays aplicáveis estão completos | rule coverage report |
| AC-003 | `uv run pytest tests/security/test_greenfield_governance.py::test_existing_path_symlink_and_partial_write_fail_closed -q` | nenhum byte preexistente muda e não sobra pacote parcial | abuse report + filesystem snapshot |
| AC-004 | `uv run pytest tests/integration/test_greenfield_governance.py::test_code_generation_waits_for_valid_governance -q` | spy do worker permanece zero até validação e invalida após tamper | gate decision record |

## Validação manual no terminal

1. `uv run aif project governance preview <EMPTY-DIRECTORY> --profile frontend-web --json`
   Esperado: exibe arquivos, profiles, evidências, regras e hashes determinísticos sem escrever no projeto atual.
2. `uv run pytest tests/integration/test_greenfield_governance.py::test_every_profile_contains_required_rule_catalog tests/security/test_greenfield_governance.py::test_existing_path_symlink_and_partial_write_fail_closed -q`
   Esperado: todos os catálogos obrigatórios passam e alvos hostis permanecem inalterados.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-034` antes de publicar o draft PR.

## Fora de escopo

Reescrever ou mesclar automaticamente `AGENTS.md`/rules/skills de projeto existente, gerar código de negócio, provisionar cloud, escolher produto/região sem input, certificar conformidade legal, publicar em app stores ou atualizar silenciosamente baselines já pinadas.

## Evidência de conclusão

Templates e golden manifests versionados, catálogo regra→profile→teste, ADR, runbook, filesystem snapshots e relatório obrigatório de [AGENTS.md](../../AGENTS.md) com baseline, diff, ACs, gates, segurança e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum arquivo real preexistente, documento remoto bruto ou segredo é capturado.

## Referências oficiais

- [W3C — WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [Google — Web Vitals](https://web.dev/articles/vitals)
- [Android — Core app quality guidelines](https://developer.android.com/docs/quality-guidelines/core-app-quality)
- [Apple — Accessibility Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/accessibility/)
- [OWASP Mobile Application Security Verification Standard](https://mas.owasp.org/MASVS/)
- [FinOps Framework](https://www.finops.org/framework/)
- [FinOps Principles](https://www.finops.org/framework/principles/)
