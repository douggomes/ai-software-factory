---
title: "ADR-0005 — Runtime de modelos exclusivamente em nuvem"
status: Accepted
date: 2026-08-12
---

# ADR-0005 — Runtime de modelos exclusivamente em nuvem

## Status

Accepted. Esta decisão complementa o [ADR-0001](0001-cli-workers-not-provider-apis.md):
a Factory continua integrando coding agents por CLI, mas somente com inferência
em nuvem. Reintroduzir inferência local ou self-hosted exige novo ADR, threat
model e task próprios.

## Contexto

O plano original reservava uma task para um planner baseado em um servidor de
inferência local. Testes prolongados no hardware de desenvolvimento mostraram
que essa rota não entrega qualidade, latência e previsibilidade suficientes
para o projeto. Mantê-la criaria um segundo protocolo de integração, novos
controles de endpoint e supply chain e um fallback com comportamento inferior,
sem valor proporcional.

OpenCode, Codex e Claude Code já são as três implementações planejadas da porta
`AgentWorker`. Seus CLIs oferecem o loop agentic, autenticação oficial e
contratos de saída que a Factory normaliza sem expor detalhes de provider ao
Core.

## Decisão

- OpenCode, Codex e Claude Code formam a allowlist fechada de runtimes de
  modelo da V1.1.
- A Factory não instala, baixa, descobre nem consulta modelos ou endpoints de
  inferência locais ou self-hosted.
- Planejamento estruturado é um papel read-only executado sobre um
  `AgentWorker` injetado; não existe adapter HTTP específico de planner nem
  chamada direta a API de provider.
- `PlanResult` continua sendo proposta não confiável, validada por schema,
  limites e gates, sem autoridade para editar, executar tools ou alterar
  policy.
- Testes e gates usam fixtures e fakes determinísticos, sem rede. Transporte ao
  provider existe somente em profile live explícito e somente no processo do
  CLI autorizado; web e rede de tools genéricos permanecem negados.
- O profile live identifica provider, região/retention aplicável, política de
  custo e classificação de dados autorizada. Somente a view mínima produzida
  pelo `ContextBuilder`, já filtrada por SecretGate, pode sair do host.
- Autenticação permanece no mecanismo oficial de cada CLI. A Factory não copia
  arquivos de sessão, não persiste tokens e mantém `no_incremental_cost=true`
  como default do profile subscription-safe.
- Quando nenhum worker cloud elegível está disponível, a política explícita de
  profile pode usar `DeterministicMinimalPlan`; não há fallback oculto para
  outro provider, endpoint ou mecanismo de inferência.

## Consequências

### Positivas

- uma única abstração de worker e uma única taxonomia de falhas para
  implementação, review, repair e planning;
- remoção do trust boundary de servidor local, descoberta de modelo e download
  de pesos;
- menos configuração dependente de hardware e menor divergência entre
  ambientes;
- testes continuam reproduzíveis sem depender de disponibilidade, quota ou
  rede de provider.

### Negativas

- execução real depende de rede, autenticação, quota e disponibilidade dos
  serviços cloud;
- não existe continuidade por modelo local durante indisponibilidade geral dos
  três CLIs;
- código e contexto autorizados atravessam uma fronteira externa; privacidade,
  residência, retenção e custo precisam ser controlados pelos profiles e pelos
  contratos dos serviços usados;
- o processo do CLI autorizado continua parte da trusted computing base; negar
  web/tools não prova isolamento de endpoint dentro de um binary comprometido.

## Controles de segurança

- preflight rejeita endpoint local, loopback, URL self-hosted e worker fora da
  allowlist;
- capability e model ID são configuração de adapter, nunca branches no Core;
- subprocesso recebe env allowlist e não expõe arquivos de autenticação em
  prompt, log, artifact ou pacote de continuação;
- execução live é opt-in, limitada por timeout, output, tokens e budget;
- context view usa allowlist, budget, classificação e provenance; arquivos
  sensíveis e segredo-canário falham antes de iniciar o CLI;
- qualquer output de modelo permanece não confiável e sem autoridade material;
- threat model é revisto antes de adicionar outro CLI, provider transport ou
  modo de inferência.

## Alternativas rejeitadas

- **Servidor de inferência local para planning:** rejeitado após avaliação de
  qualidade, latência e previsibilidade no ambiente-alvo.
- **Chamada direta a APIs de provider:** permanece rejeitada pelo ADR-0001 para
  evitar reimplementar o loop agentic e ampliar a autoridade da Factory.
- **Fixar um único coding agent cloud:** rejeitado porque elimina failover e
  aumenta dependência operacional de um fornecedor.
