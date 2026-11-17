# homelab-platform — Guia do Agente (HUB)

Este repositório define a **Camada 0 (Proxmox VE)** e a **Camada 1 (HUB — `VM 100 homelab-hub`)**, além do bootstrap do cluster **K3s + FluxCD (`VM 200 homelab-k3s`)** e do **Registry Declarativo de Spokes**.

## Fronteiras do Repositório

- **O que pertence aqui:**
  - `infrastructure/proxmox/`: OpenTofu declarativo das VMs `100` (`homelab-hub`) e `200` (`homelab-k3s`), firewall do host Proxmox e VMs, mapeamentos USB/PCI (HD 18 TB + iGPU Intel QuickSync) e backups diários `vzdump` no `nvme-secondary`.
  - `infrastructure/ansible/`: Playbooks idempotentes para Ubuntu 24.04 (`hub` com Docker + Tailscale; `k3s` com mounts UUID via `systemd RequiresMountsFor`, `/dev/dri`, K3s, `sops-age` e `flux bootstrap`).
  - `infrastructure/hub/`: Stack Docker Compose da `VM 100 homelab-hub` (Traefik com ACME Cloudflare DNS-01 `*.greis.dev.br`, CoreDNS Split-DNS, Authelia SSO, Homepage, Prometheus + Grafana + Loki + Alertmanager).
  - `kubernetes/`: Bootstrap FluxCD (`clusters/homelab/`), agentes de observabilidade e `prometheus-mcp` (`platform/`), registro de Spokes (`spokes-registry/`) e blueprint `templates/spoke-starter/`.
  - `docs/`: ADRs (`docs/adr/`) e runbook de cutover (`docs/cutover-runbook.md`).
- **O que é PROIBIDO aqui:**
  - Nunca colocar código, manifests de aplicação, regexes de API, flags de cookie ou regras de negócio específicas de um Spoke (como Jellyfin, \*arr ou Hermes) neste repositório.
  - Nunca adicionar diários datados de execução neste `AGENTS.md` ou no `README.md` (use `docs/adr/`).
  - Nunca criar worktrees ou pastas de lixo (`.artifacts/`, `.runtime/`, `.worktrees/`, `backup/`).
  - Nunca desabilitar logs (`error_log /dev/null`) nem commitar `.env` ou chaves privadas em texto claro (apenas `*.example` ou `*.sops.yaml`).

## Validação Local Obrigatória

Antes de qualquer commit em `homelab-platform`:

```bash
node scripts/validate.mjs
```

O validador verifica ausência de pastas temporárias e segredos em texto claro e executa `kubectl kustomize` em todos os diretórios Kubernetes (`clusters/homelab`, `platform`, `spokes-registry`, `spokes-registry/vaultwarden` e `templates/spoke-starter`).

## Como Registrar um Novo Spoke

1. Copie `kubernetes/templates/spoke-starter/` como base no novo repositório do Spoke (`homelab-<nome>`).
2. Adicione o par `GitRepository` + `Kustomization` em `kubernetes/spokes-registry/` (referenciando `./kubernetes` do repo do Spoke com descriptografia SOPS).
3. Se o domínio exigir proteção ou exposição via Hub, declare apenas o encaminhamento genérico no Traefik (`routes-k3s.yml`) e o card no Homepage (`homepage/services.yaml`).
