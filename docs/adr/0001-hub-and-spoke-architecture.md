# ADR-0001: Arquitetura Hub & Spoke sobre Proxmox VE, K3s e FluxCD

- **Status:** Aceito
- **Contexto:** O modelo anterior utilizava 5 VMs Ubuntu isoladas (`110`, `111`, `120`, `121`, `122`) em um host com 15,49 GiB de RAM, múltiplas stacks Compose desconexas e scripts SSH imperativos em `.artifacts/`, causando OOM kills frequentes, *split-brain* no Git e alto custo de RAM para cada novo serviço.

## Decisão

1. **Separação em 2 VMs no Proxmox (`pve01`):**
   - **`VM 100 (homelab-hub)` — 2,5 GiB RAM:** Infraestrutura crítica sempre disponível (Tailscale, CoreDNS, Traefik Hub Ingress, Authelia SSO, Homepage, Prometheus, Grafana, Loki, Alertmanager). Fica isolada para que manutenção ou reinicialização do cluster de aplicações nunca derrube VPN, DNS ou observabilidade.
   - **`VM 200 (homelab-k3s)` — 10,0 GiB RAM:** Cluster K3s single-node para todos os **Spokes**, isolados por **Namespace** + `NetworkPolicy` default-deny + `ResourceQuota`. Reservar ~3,0 GiB para o hypervisor Proxmox evita disputa de memória e permite escalar novos Spokes sem overhead de novos SOs Ubuntu.
2. **Ingress e TLS Automatizados:**
   - Domínio `greis.dev.br` delega apenas Nameservers (NS) para **Cloudflare (DNS-only, sem proxy HTTP)** para automação `DNS-01` do wildcard `*.greis.dev.br` no Traefik.
   - Rotas do Hub são separadas explicitamente entre `internal-only` (protegidas por `private-network-only` + Authelia `sso-auth`) e `external-ready` (`jellyfin.greis.dev.br` e `overseer.greis.dev.br`, prontas para eventual túnel Pangolin/WireGuard sem retrabalho), além do listener LAN `:8096` para TVs da casa.
3. **GitOps e Segredos:**
   - Proxmox e `VM 100` gerenciados via **OpenTofu + Ansible**.
   - Todos os Spokes em K3s reconciliados por **FluxCD + SOPS/Age** diretamente das branches `main` de seus respectivos repositórios.
   - **Vaultwarden** (`spoke-vaultwarden`) é preparado como o Spoke #3 para senhas pessoais, enquanto segredos de infraestrutura permanecem criptografados no Git via `SOPS/Age` para garantir boot autônomo pós-queda de energia.
4. **Padrão MCP-por-Spoke para IA (`homelab-hermes`):**
   - O agente pessoal (`spoke-hermes`) consome serviços e observabilidade exclusivamente via endpoints MCP internos autenticados e liberados por `NetworkPolicy` (`arr-mcp` no `spoke-mediaserver` e `prometheus-mcp` em `platform-observability`), proibindo SSH ou acesso ao socket Docker.

## Consequências

- Adição de novos Spokes não consome memória de nova VM.
- Zero código Python/JS customizado de governança (aposentadoria do portal Órbita e do controlador customizado do mediaserver).
- Expansão futura para um 2º ou 3º nó físico requer apenas ingressar uma nova VM worker ao cluster K3s existente.
