# ADR-0004: Novos Spokes Operacionais (`spoke-overseer` e `spoke-kanban`), Renomeação do Seerr para `jellyseerr` e Alocação no Worker `M710q`

- **Status:** Aceito / Implementado nos repositórios dos Spokes (evolui [ADR-0001](0001-hub-and-spoke-architecture.md) e [Plano M710q](../../../docs/plans/multi-node-m710q-worker-plan.md))
- **Contexto:** O ecossistema precisa absorver dois novos domínios operacionais sem violar o desacoplamento Hub ↔ Spoke nem sobrecarregar a `VM 200 (homelab-k3s)` onde roda o `spoke-mediaserver`:
  1. Um transcritor contínuo de reuniões do Google Meet baseado no [`opedromartins/entmoot`](https://github.com/opedromartins/entmoot) (`spoke-overseer`), tomando o subdomínio `overseer.greis.dev.br` hoje atribuído ao Seerr de mídia.
  2. Um quadro Kanban self-hosted integrado via MCP ao Hermes e acessível aos agentes de código locais no Desktop Windows (`spoke-kanban`).

## Decisão

1. **Migração de Subdomínio do Seerr de Mídia (`overseer` → `jellyseerr`):**
   - O aplicativo Seerr em `spoke-mediaserver` passa a responder em **`https://jellyseerr.greis.dev.br`**, liberando `overseer.greis.dev.br` para o novo `spoke-overseer`.
   - A atualização abrange exclusivamente o roteador `spokes-external-ready` em `homelab-platform/infrastructure/hub/traefik/dynamic/routes-k3s.yml`, o `mediaserver-ingress` em `homelab-mediaserver`, os links no `homelab-dashboard` e referências documentais.

2. **`spoke-overseer` (`homelab-overseer` em `https://overseer.greis.dev.br`):**
   - Utiliza BFF em Node.js (`apps/bff`) + Web UI Vectorheart (`apps/web`) + sidecar Python Parakeet ONNX `int8` (`asr-worker`) + SQLite persistido em PVC, expondo Web UI, API REST, WebSocket de ingestão e o servidor MCP interno `overseer-mcp` (`ClusterIP :6061/mcp`).
   - **Captura v1:** extensão Chromium (Manifest V3 com Service Worker + keepalive/offscreen) derivada dos scripts de captura Meet do `opedromartins/entmoot`, enviando áudio e sinais de falante via `wss://overseer.greis.dev.br/ws/ingest` com Bearer Token.
   - **Autenticação bipartida no Hub Traefik:** rotas HTTP (`/`, `/api/*`) protegidas por `private-network-only` + Authelia `sso-auth`; rota `/ws/ingest` protegida por `private-network-only` + `security-headers` e validação no backend de Bearer Token (SOPS) e allowlist de `Origin` da extensão (evitando desconexão de chamadas longas por expiração de cookie SSO).
   - **Motor ASR por projeto & retenção:** selecionável entre `local_parakeet_int8` (CPU no `M710q`, descarregado após 5 min de ociosidade — obrigatório para projetos corporativos/privados) e `api_external` (OpenAI/Groq via SOPS). Áudio bruto é processado apenas em memória e descartado imediatamente após transcrição na v1.

3. **`spoke-kanban` (`homelab-kanban` em `https://kanban.greis.dev.br`):**
   - Adota o **[`usekaneo/kaneo`](https://github.com/usekaneo/kaneo)** (MIT, `v2.50.0+`, imagem oficial pré-compilada pinada por `@sha256`) no modelo **Board Central no Cluster + Orquestração de Worktrees no Desktop Windows**:
     - No cluster (`spoke-kanban`): `postgres:16-alpine` (PVC persistente + `CronJob` diário de `pg_dump`), `kanban-kaneo` (`:5173`, Workspaces isolados, subtasks, dependências, prioridades, labels, integração GitHub/GitLab/Gitea e endpoint MCP nativo `/api/mcp`) e adaptador Zero-Trust `kanban-mcp` (`ClusterIP :6062/mcp` Streamable-HTTP para o Hermes com `allowedWorkspaceId`/`allowedProjects` e `confirm_token` em 2 etapas).
     - No Desktop Windows (via Tailscale): **Emdash** (`generalaction/emdash`, Apache-2.0) ou CLIs locais (Claude Code, Codex, Gemini CLI, OpenCode) em **git worktrees** isolados, conectados ao Kaneo via MCP nativo (`https://kanban.greis.dev.br/api/mcp` ou `npx @kaneo/mcp`).
   - **Fronteira de Rede no Hub Traefik:** protegido por `private-network-only` + `security-headers` (exclusivo LAN/Tailscale, sem `sso-auth` do Authelia), preservando sessões, API Keys e OAuth/PKCE nativos do endpoint `/api/mcp`.

4. **Alocação de Hardware no Worker `Lenovo M710q` (`worker-01`):**
   - Ambos os Spokes são agendados exclusivamente no nó `homelab-k3s-worker-01` via `nodeSelector` + `toleration` (`homelab.greis.dev.br/tier=auxiliary`), mantendo a `VM 200` isolada para `spoke-mediaserver` (HD 18 TB + iGPU 10ª gen) e preparando o caminho para o upgrade do `M710q` para 16 GB RAM + 1 TB SSD.
   - Os registros em `kubernetes/spokes-registry/` iniciam com `suspend: true` até a conclusão do provisionamento físico do `M710q`, da troca do ingress do Seerr e da geração dos segredos cifrados `secrets/*.sops.yaml`.

## Alternativas Consideradas

- **`BloopAI/vibe-kanban` (avaliação inicial):** descartado na implantação após verificação prática de que a `v0.1.44+`/`v0.1.46` desativou as rotas de projeto no frontend (`ProjectSunsetPage`), exige compilação Rust `nightly` + ElectricSQL + cliente Desktop preso em `v0.1.43`, tornando sua manutenção cara e frágil.
- **Plane:** exige Postgres + Redis + MinIO + múltiplos workers (~1,5–2,5 GiB RAM idle), excessivo para o `M710q`.
- **Vikunja:** leve (~50–100 MiB RAM), mas voltado a listas de tarefas em vez de issue tracker de engenharia estilo Linear com MCP nativo e Workspaces como o Kaneo.
- **Expor o `/api/mcp` nativo direto ao Hermes:** o endpoint nativo do Kaneo confia no escopo amplo da API Key do usuário; manter o adaptador fino `kanban-mcp` em Streamable-HTTP dentro de `spoke-kanban` garante enforcement server-side de `allowedWorkspaceId`/`allowedProjects` por profile Hermes e `confirm_token` em 2 etapas.

## Consequências

- **Zero impacto no `spoke-mediaserver`:** apenas uma troca declarativa de hostname do Seerr antes de tirar `spoke-overseer` de `suspend: true`.
- **Menor pegada no `M710q`:** o Kaneo consome apenas `postgres:16-alpine` + 1 container Node/nginx (sem ElectricSQL), com imagem oficial pré-compilada do GHCR.
- **Manutenção contínua de adaptadores:** o time mantém os adaptadores leves `overseer-mcp`/`transcritor` e `kanban-mcp`, além das imagens pinadas por `@sha256`.
