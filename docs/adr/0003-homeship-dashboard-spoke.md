# ADR-0003: HomeShip Control como Spoke (`spoke-dashboard`) e Descomissionamento do `hub-homepage`

- **Status:** Aceito (Em Produção — evolui [ADR-0001](0001-hub-and-spoke-architecture.md))
- **Contexto:** Na [ADR-0001](0001-hub-and-spoke-architecture.md), o painel inicial `hub-homepage` rodava como container estático na `VM 100 (homelab-hub)`. Essa abordagem consumia memória na VM de 2,5 GiB do Hub e exigia manutenção manual de `services.yaml` no repositório `homelab-platform` a cada novo Spoke ou rota — criando acoplamento entre a infraestrutura compartilhada e o catálogo de aplicações.

## Decisão

1. **Portal Operacional como Spoke Independente (`homelab-dashboard` → `spoke-dashboard`):**
   - O dashboard operacional **HomeShip Control** passa a viver em repositório e namespace dedicados na `VM 200 (homelab-k3s)`, reconciliado via **FluxCD + SOPS/Age** e sujeito às mesmas regras de isolamento (`NetworkPolicy` default-deny, `ResourceQuota`, `readOnlyRootFilesystem: true`).
   - O `homelab-platform` registra apenas o par `GitRepository` + `Kustomization` em `kubernetes/spokes-registry/dashboard.yaml` e fornece telemetria genérica de infraestrutura (API/métricas somente-leitura do Traefik Hub em `172.28.64.100:8082` restrita à `VM 200` pelo firewall Proxmox, `node_exporter` no `pve01` e `kube-state-metrics`).
2. **Auto-Discovery Nativo sem Hardcoding:**
   - Novos Spokes são descobertos dinamicamente via Kubernetes Watch (labels `homelab.greis.dev.br/spoke: "true"` e annotations `homeship.greis.dev.br/*`, padronizadas em `templates/spoke-starter/`) combinados ao inventário de routers do Hub Traefik (`:8082`).
   - Capacidades opcionais (`media`, `copilot`) ligam e desligam cards/decks automaticamente conforme a presença dos respectivos namespaces, distinguindo **Spoke removido** (ocultado) de **Spoke com pods offline** (mantido em alerta).
3. **Promoção para o Domínio Principal e Descomissionamento do `hub-homepage`:**
   - Após validação em canário (`https://homeship.greis.dev.br`), a rota explícita `hub-homepage` foi removida de `routes-hub.yml`, permitindo que `https://homelab.greis.dev.br` caia diretamente no wildcard genérico `spokes-internal-sso` (`private-network-only` + Authelia ForwardAuth + `security-headers`), com `Middleware/hub-only` (`172.28.64.100/32`) no Ingress do K3s.
   - O container `hub-homepage`, sua configuração (`infrastructure/hub/homepage/`) e as tasks de provisionamento em `playbooks/hub.yml` foram removidos da `VM 100`.

## Consequências

- **Zero acoplamento Hub ↔ Spoke:** adicionar ou remover Spokes não exige editar manifestos de dashboard no `homelab-platform`.
- **Menor pressão de RAM na `VM 100`:** menos um container rodando continuamente no Hub, preparando terreno para a remoção opcional do `hub-grafana`.
- **Entrega contínua determinística:** pushes em `homelab-dashboard` publicam imagem no GHCR e fixam automaticamente o digest `@sha256:...` no `Deployment` reconciliado pelo FluxCD.
