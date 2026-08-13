---
title: "TASK-033 — Gateway confiável de documentação oficial"
task_id: TASK-033
release: "V0.5"
status: planned
depends_on: [TASK-024]
baseline_commit: "TO_BE_PINNED"
risk_level: critical
---

# TASK-033 — Gateway confiável de documentação oficial

> [!important] Contrato de execução por IA
> Execute somente quando `status: ready`, seguindo [AGENTS.md](../../AGENTS.md), [engineering-standards.md](engineering-standards.md) e [security-review.md](security-review.md). O agente não pode alterar este contrato nem ampliar paths, autoridade, rede, budget ou defaults.

## Valor entregue

A Factory pesquisa documentação atual e específica de versão por uma porta auditável, prioriza fontes oficiais e usa o Context7 apenas como fonte complementar. O resultado é uma evidência limitada, cacheável, reproduzível e segura para fundamentar planejamento, geração de regras e implementação sem conceder navegação arbitrária aos workers.

## Definition of Ready

- [ ] Todas as tasks de `depends_on` foram aprovadas com evidência.
- [ ] `baseline_commit` foi substituído por SHA de 40 caracteres e confere com o checkout limpo.
- [ ] Todas as precondições abaixo foram verificadas.
- [ ] Interfaces/defaults continuam compatíveis com os artifacts das dependências.
- [ ] Não existe outra task `ready` nem conflito de arquivos.

## Precondições

- TASK-024 e o dossier da V0.4 estão aprovados.
- `ProcessRunner`, `ArtifactStore`, configuração, telemetria e redaction possuem contract tests aprovados.
- As integrações oficiais do Context7 ainda expõem `resolve-library-id` e `query-docs`; qualquer incompatibilidade exige atualizar o ADR antes de implementar.
- A suíte padrão permanece totalmente offline; smoke com rede e credencial é opt-in e não participa dos gates obrigatórios.
- Documentos remotos, respostas MCP, snippets e metadados são entradas não confiáveis e nunca concedem autoridade.

## Arquivos permitidos

- `src/ai_software_factory/core/documentation_models.py`
- `src/ai_software_factory/ports/documentation.py`
- `src/ai_software_factory/application/documentation_research.py`
- `src/ai_software_factory/adapters/documentation/**`
- `src/ai_software_factory/config.py`
- `src/ai_software_factory/cli.py`
- `schemas/documentation-evidence.v1.json`
- `tests/contract/documentation/**`
- `tests/integration/test_documentation_gateway.py`
- `tests/security/test_documentation_gateway.py`
- `docs/runbooks/documentation-research.md`
- `docs/adr/0009-trusted-documentation-research.md`
- `pyproject.toml`
- `uv.lock`

Qualquer outro path é proibido, inclusive arquivo gerado não listado. `pyproject.toml` e `uv.lock` só podem mudar juntos quando o ADR demonstrar que a biblioteca cliente é indispensável; a preferência é reutilizar as portas e dependências existentes.

## Arquivos proibidos

- `docs/planejamento/**`
- `.env*`, `**/auth.json`, keychain, tokens, chaves e credenciais
- paths fora da raiz ou alcançados por symlink
- código, SPEC, prompt ou diff do projeto alvo em consultas externas
- arquivos do usuário não relacionados já modificados

## Interfaces e contratos

| Símbolo/contrato | Definição fechada |
|---|---|
| `DocumentationResearch.research(request: DocumentationRequest) -> DocumentationEvidence` | Autoriza, consulta fontes pelo registry, aplica precedência, limita e persiste somente evidência sanitizada. |
| `DocumentationSource.retrieve(request: AuthorizedDocumentationRequest) -> SourceDocument` | Porta ISP implementada por fonte oficial HTTPS, Context7 ou cache; nunca recebe credencial no domínio. |
| `DocumentationPolicy.authorize(request: DocumentationRequest) -> AuthorizedDocumentationRequest` | Valida biblioteca, versão, pergunta, classificação, fonte, rede e budget antes de qualquer I/O. |
| `DocumentationEvidence v1` | Biblioteca, versão solicitada/resolvida, claim, fonte, URL ou Context7 ID, `retrieved_at`, hash do conteúdo, cache key, policy hash e trechos limitados. |
| `aif docs sources|research` | `sources` é read-only/offline; `research` aceita somente biblioteca/version/query estruturadas e perfil de rede explícito. |

As portas pertencem ao domínio da Factory; seleção de adapter ocorre no composition root. Core/Application não ramificam por nome de Context7, host, fornecedor ou biblioteca.

## Defaults e decisões fechadas

| Chave | Valor normativo |
|---|---|
| `documentation.mode` | `offline`; acesso remoto exige perfil `docs-research-live` aprovado |
| `documentation.precedence` | documentação oficial versionada → repositório/release notes oficiais → Context7 |
| `documentation.context7.endpoint` | `https://mcp.context7.com/mcp` fixo; endpoint configurável é proibido na V1.1 |
| `documentation.context7.tools` | somente `resolve-library-id` e `query-docs` |
| `documentation.official_domains` | allowlist versionada por biblioteca; HTTPS, porta 443 e path prefix aprovados |
| `documentation.redirects` | zero; redirect falha fechado |
| `documentation.max_queries_per_task` | 8 |
| `documentation.timeout_seconds` | 20 por consulta; 60 total por pesquisa |
| `documentation.max_response_bytes` | 524288 por fonte |
| `documentation.max_evidence_bytes` | 131072 por artifact |
| `documentation.max_excerpt_chars` | 1200 por fonte e sem cópia integral |
| `documentation.cache_ttl_hours` | 168; versão, source ID, query hash e policy hash compõem a chave |
| `documentation.query_data` | somente nome público da biblioteca, versão e pergunta técnica genérica |
| `documentation.critical_claims` | segurança, autenticação, privacidade, billing, migration e breaking change exigem fonte oficial; Context7 isolado resulta `insufficient_evidence` |
| `documentation.cost` | budget explícito, sem retry oculto; rate limit retorna falha normalizada |

DNS é resolvido e revalidado no uso; loopback, link-local, redes privadas, Unix socket, metadata endpoints, IP literal e host fora da allowlist são negados. A API key opcional do Context7 permanece no adapter e nunca entra em request, evento, log ou artifact.

## Passos de implementação

1. Fechar modelos imutáveis, schema v1, portas segregadas e política determinística.
2. Implementar cache e adapters de documentação oficial/Context7 atrás do registry do composition root.
3. Aplicar allowlist de host/path, proteção SSRF/DNS rebinding, limites, redaction, budget e provenance.
4. Integrar CLI e telemetria sanitizada sem expor payload remoto bruto.
5. Criar fixtures offline, contract/security tests, ADR e runbook com smoke live separado.

## Riscos e controles

| Risco | Controle obrigatório | Teste negativo |
|---|---|---|
| SSRF, redirect ou DNS rebinding alcança recurso interno | endpoint e domínio fechados, resolução pública revalidada, zero redirect | `test_ssrf_redirect_and_rebinding_fail_before_network` |
| Prompt injection em documento remoto altera policy | conteúdo marcado como dado, schema/limite, nenhuma ação derivada sem policy/gate | `test_untrusted_document_cannot_grant_authority` |
| Código ou segredo é enviado na query | tipo de request reduzido, SecretGate e canário antes do adapter | `test_secret_or_project_content_never_reaches_source` |
| Context7 desatualizado vira verdade crítica | precedência e exigência de fonte oficial para claims críticas | `test_context7_alone_is_insufficient_for_critical_claim` |
| Rede/custo/output cresce sem limite | modo offline, budgets, timeout, bytes e cache determinístico | `test_budget_timeout_and_oversize_fail_closed` |
| Evidência viola licença ou expõe conteúdo excessivo | trechos curtos, URL/hash/proveniência, sem espelhamento integral | `test_evidence_enforces_excerpt_limit` |

## Critérios de aceite

- [ ] **AC-001** — A mesma pesquisa versionada sobre fixtures produz `DocumentationEvidence v1` byte a byte estável, com fonte, URL/Context7 ID, timestamps injetados, hashes, precedência e cache key verificáveis.
- [ ] **AC-002** — Offline é o default, cache válido evita nova chamada, cache expirado não habilita rede e budgets/timeout/rate limit falham explicitamente sem retry oculto.
- [ ] **AC-003** — SSRF, redirect, DNS rebinding, output malformado/excessivo, prompt injection, segredo-canário e conteúdo do projeto são bloqueados antes de efeito não autorizado ou persistência.
- [ ] **AC-004** — Claim crítica sem fonte oficial resulta `insufficient_evidence`; Context7 complementa contexto, mas nunca eleva sua própria autoridade.

## Matriz de verificação

| Critério | Comando exato | Teste/asserção | Evidência persistida |
|---|---|---|---|
| AC-001 | `uv run pytest tests/contract/documentation tests/integration/test_documentation_gateway.py::test_versioned_evidence_and_cache_are_deterministic -q` | duas execuções equivalentes geram o mesmo schema/hash | fixture `documentation-evidence.v1.json` sanitizada |
| AC-002 | `uv run pytest tests/integration/test_documentation_gateway.py::test_offline_cache_budget_and_rate_limit -q` | spies provam zero rede/retry fora da policy | eventos normalizados + cache manifest |
| AC-003 | `uv run pytest tests/security/test_documentation_gateway.py::test_ssrf_secret_and_untrusted_output_fail_closed -q` | canários e endpoints hostis não alcançam adapter/store | abuse report sanitizado |
| AC-004 | `uv run pytest tests/integration/test_documentation_gateway.py::test_critical_claim_requires_official_evidence -q` | Context7 isolado retorna `insufficient_evidence` | decision record com source precedence |

## Validação manual no terminal

1. `uv run aif docs sources --json`
   Esperado: lista apenas fontes, domínios, budgets e modo offline aprovados, sem segredo ou chamada de rede.
2. `uv run pytest tests/integration/test_documentation_gateway.py::test_versioned_evidence_and_cache_are_deterministic tests/security/test_documentation_gateway.py::test_ssrf_secret_and_untrusted_output_fail_closed -q`
   Esperado: evidência reproduzível passa e entradas hostis falham sem rede/persistência não autorizada.

O agente imprime esta seção com `python3 scripts/show_manual_validation.py TASK-033` antes de publicar o draft PR.

## Fora de escopo

Browser genérico, busca web aberta, crawling, execução de snippets, indexação de repositório privado, RAG vetorial, atualização autônoma de dependência, escolha autônoma de licença e rede durante a suíte padrão.

## Evidência de conclusão

Schema/fixtures versionados, ADR, runbook, contract/security reports e relatório obrigatório de [AGENTS.md](../../AGENTS.md) contendo baseline, diff, cada AC com comando/resultado/evidência, gates globais, segurança e riscos residuais. Após os gates, o agente cria commit, publica a branch e abre/atualiza automaticamente um draft PR para `dev` usando `gh`. Nenhum documento remoto bruto, transcript, código proprietário ou segredo é persistido.

## Referências oficiais

- [Context7 — repositório e tools oficiais](https://github.com/upstash/context7)
- [Context7 — clientes suportados](https://context7.com/docs/resources/all-clients)
- [Context7 — CLI](https://context7.com/docs/clients/cli)
- [OWASP Top 10 for LLM Applications — Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
