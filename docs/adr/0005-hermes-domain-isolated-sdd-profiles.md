# ADR-0005: Isolamento Multi-Domínio no Hermes (Profiles SDD), Acesso Governado a Repositórios (`repo-mcp`) e Separação entre Análise e Execução de Código

- **Status:** Proposto (Validado via `/grill-me` — complementa [ADR-0004](0004-overseer-and-kanban-spokes.md))
- **Contexto:** O pipeline de engenharia assistida por IA envolve tanto **projetos pessoais** quanto **projetos de trabalho/clientes**, frequentemente com políticas rígidas de sigilo de código, transcrições e credenciais. O `spoke-hermes` atual opera com apenas um profile (`default`), shell desativado e acesso via WhatsApp/HomeShip ao `arr-mcp` e `prometheus-mcp`. Misturar transcrições corporativas, tokens Git de clientes e contexto de projetos pessoais em uma única memória/sessão ou conceder shell direto ao Hermes no servidor criaria risco severo de vazamento cruzado e mutação não revisada.

## Decisão

1. **Separação Estrita de Papéis (Analista SDD no Servidor vs. Executor no Desktop):**
   - O `spoke-hermes` mantém `terminal`, `code_execution` e `file` **desativados**, atuando exclusivamente como **Analista SDD** por meio de servidores MCP tipados.
   - Toda execução de código, instalação de dependências, testes locais e criação de git worktrees acontece exclusivamente no **Desktop Windows** sob disparo e supervisão do proprietário (ex.: via Emdash / worktrees locais conectados ao Kaneo).

2. **Isolamento por Domínio/Cliente via Hermes Profiles:**
   - O profile `default` (`homelab`) permanece inalterado com `delegation.backend: model_map` (`rotina`/`diagnostico`/`visual`) para mídia, observabilidade e futuro `ops-mcp`.
   - Cada domínio/cliente recebe um **Hermes Profile dedicado** (`sdd-personal`, `sdd-work-<cliente>`) sob o gateway multiplexado em `/opt/data/profiles/<profile>/`, isolando fisicamente:
     - memória persistente e histórico de sessões;
     - `SOUL.md`, `AGENT_INSTRUCTIONS.md` e skills SDD (`sdd-architect`);
     - provedor/modelo/conta LLM (permitindo uso de conta corporativa separada em clientes);
     - Bearer Tokens individuais para `overseer-mcp`, `repo-mcp` e `kanban-mcp`.
   - **Roteamento Determinístico e Proibição de Vazamento no WhatsApp:** o `spoke-overseer` mapeia `project_id → hermes_profile` de forma declarativa e direciona o usuário diretamente para a sessão Web do profile correspondente (`/p/<profile>/` no Hermes/HomeShip). Chats de trabalho/clientes **não** tramitam pelo WhatsApp pessoal nem por um chat pai compartilhado via `profile_routes`, eliminando contaminação de histórico.

3. **Governança de Repositórios via `repo-mcp` (`:6063/mcp`) + `confirm_token`:**
   - Novo servidor MCP interno (`repo-mcp`) comunica-se diretamente com as APIs do GitHub e GitLab usando tokens fine-grained por domínio/projeto armazenados em SOPS (sem clones persistentes ou chaves SSH amplas no Hermes).
   - Operações de leitura (`list_project_repos`, `get_repo_tree`, `read_repo_file`, `search_repo_code`, `list_recent_prs`) são diretas; a publicação do pacote SDD (`propose_sdd_pr` → `apply_sdd_pr`) exige **handshake `confirm_token` em 2 etapas** (TTL 5 min, vinculado ao hash dos argumentos), criando uma branch `docs/sdd-<slug>` e abrindo Pull Request estruturada — nunca fazendo push direto em `main`.

4. **Enforcement Server-Side nos MCPs (`overseer-mcp`, `repo-mcp`, `kanban-mcp`):**
   - Cada servidor MCP valida o Bearer Token do profile chamador e restringe todas as consultas e mutações ao conjunto `allowed_projects` / `allowed_repos` / `allowed_workspace_id` vinculado àquele token. Mesmo diante de prompt injection em transcrições de terceiros ou código-fonte, um profile não consegue ler nem escrever recursos de outro domínio.

5. **Duplo Gate Humano no Ciclo SDD → Código:**
   - **Gate 1 (SDD):** revisão interativa no chat Web do profile Hermes + `confirm_token` antes de abrir a PR de SDD e criar cards no Kaneo (`spoke-kanban`).
   - **Gate 2 (Código):** disparo manual do agente em worktree no Desktop Windows; subtasks descobertas pelo agente durante a implementação entram em `To Do` sem auto-delegação; code review, teste funcional e merge da PR de código são estritamente humanos antes de concluir o card (`Done`).

## Alternativas Consideradas

- **Profile único `sdd-architect` para todos os projetos:** descartado porque a memória de longo prazo e o histórico de sessões do Hermes poderiam misturar decisões, nomes de projetos e trechos entre clientes distintos.
- **Um Pod/Deployment K8s separado do Hermes por cliente:** garante isolamento adicional de processo, mas multiplica consumo de RAM e manifestos GitOps a cada novo cliente. Os profiles nativos do Hermes multiplexados somados ao enforcement server-side nos MCPs atingem o equilíbrio ideal, mantendo a opção de promover um cliente ultra-crítico para pod dedicado no futuro sem mudar os contratos MCP.
- **Ponte via Desktop Runner para leitura/escrita de repos:** descartada por acoplar a etapa de análise SDD à disponibilidade do Desktop ligado; a integração via API GitHub/GitLab com tokens fine-grained em SOPS permite gerar e revisar o SDD a qualquer momento no HomeServer.

## Consequências

- **Zero vazamento entre domínios:** credenciais, memória, contexto e provedores LLM ficam segregados por domínio/cliente.
- **Auditabilidade integral:** toda transição crítica (`apply_sdd_pr`, criação de cards via `kanban-mcp`, abertura de PR de código) deixa trilha rastreável no Git, no Vibe Kanban e nos logs do Loki.
- **Disciplina de onboarding por cliente:** adicionar um novo domínio exige apenas declarar o profile no GitOps do `homelab-hermes`, emitir seus tokens SOPS e registrar `allowed_projects`/`allowed_repos`/`allowed_org_id` nos MCPs.
