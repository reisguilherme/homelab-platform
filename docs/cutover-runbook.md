# Runbook de Cutover — Etapa 5 (Janela Assistida no Proxmox)

Este roteiro executa a transição limpa para `VM 100 (homelab-hub)` + `VM 200 (homelab-k3s)` **sem apagar as VMs antigas (`110`, `111`, `120`, `121`) até a validação completa em produção**.

## Pré-requisitos Offline (Antes da Janela)

1. **Delegação DNS Cloudflare (sem proxy HTTP):**
   - No painel do Registro.br, apontar os Nameservers (NS) de `greis.dev.br` para a Cloudflare (plano gratuito).
   - Criar na Cloudflare um API Token com permissão `Zone:DNS:Edit` apenas para a zona `greis.dev.br` (`CF_DNS_API_TOKEN`).
   - Configurar os registros `A` iniciais apontando `*.greis.dev.br` para o IP Tailscale da futura `homelab-hub` (com proxy nuvem cinza / **DNS-only**).
2. **Chave Mestra SOPS/Age e Padronização de Secrets (`root` + `ROOT_PASSWORD`):**
   - Garantir `~/.config/sops/age/keys.txt` na estação de trabalho (backup seguro no gerenciador de senhas, **nunca** nos repositórios) e a respectiva chave pública no `.sops.yaml` dos 3 repositórios.
   - Criar `secrets/*.sops.yaml` a partir dos `*.example.yaml` e criptografar com `sops -e -i`:
     - **Usuário e senha unificados (`ROOT_USERNAME=root` + `ROOT_PASSWORD`)**: definir a mesma senha em `/opt/homelab-hub/.env` (Grafana + Authelia), `mediaserver-secrets.sops.yaml` (`arr-mcp` UI, `bazarr`, referência `qbittorrent` no `arr-mcp`) e `hermes-secrets.sops.yaml`.
     - **Chaves arbitrárias (gerar novas aleatórias)**: `RADARR_API_KEY`, `SONARR_API_KEY`, `PROWLARR_API_KEY` e `BAZARR_API_KEY` (32 chars hex cada — injetadas nativamente por env var / `sync-auth`), `ARR_MCP_HERMES_TOKEN` (`amcp_<64 hex>` — idêntico entre `mediaserver` e `hermes`; o `arr-mcp` calcula `sha256:` automaticamente no startup) e `AUTHELIA_*` (64 chars hex).
     - **Chaves externas (não arbitrárias)**: `CF_DNS_API_TOKEN` (Cloudflare), `PVE_METRICS_TOKEN_VALUE` (Proxmox) e `OPENAI_API_KEY` (OpenAI).
     - **Chaves ligadas ao banco migrado (`appdata`)**: `JELLYFIN_API_KEY` e `SEERR_API_KEY` (reaproveitar os valores preservados em `.private-vault/` ou gerar novas chaves na UI após a restauração e atualizar `mediaserver-secrets.sops.yaml`).
3. **Subir branches `main` (e tags `legacy-2026-11`) para o GitHub** nos repositórios `homelab-platform`, `homelab-mediaserver` e `homelab-hermes`.

## Passo 1 — Preparação do `nvme-secondary` e Mapeamentos no Proxmox (`pve01`)

1. Conferir pelo shell do Proxmox o dispositivo exato do 2º SSD NVMe (512 GB, preservado desmontado até aqui) e o dispositivo PCI da iGPU Intel (`lspci -nn | grep -i vga`).
2. Inicializar o 2º NVMe no Proxmox como datastore `nvme-secondary` habilitando os tipos `images,rootdir,backup` (ex.: `pvesm add dir nvme-secondary --path /mnt/pve/nvme-secondary --content images,backup,iso,snippets`).
3. Criar no Datacenter do Proxmox os Resource Mappings:
   - USB Mapping (`media-hdd-18tb`) apontando pelo Vendor/Product ou porta física para o HD USB de 18 TB.
   - PCI Mapping (`intel-igpu-qsv`) apontando para o device PCI da Intel UHD iGPU.
4. Garantir imagem cloud-init Ubuntu 24.04 (`noble-server-cloudimg-amd64.img`) em `/var/lib/vz/template/iso/` ou template VM no Proxmox.

## Passo 2 — Snapshot Consistente de Appdatas e Quiescência das VMs Antigas

1. Na VM antiga `120 (mediaserver-core)`:
   - Pausar downloads/containers de escrita (`docker compose stop` no core/mcp) mantendo os torrents concluídos preservados no `/srv/appdata/core/qbittorrent` e os bancos SQLite consistentes.
   - Copiar `/srv/appdata/core/{radarr,sonarr,prowlarr,bazarr,seerr,qbittorrent}` via `rsync -aHAX` para área de staging no `/mnt/pve/nvme-secondary/migration-appdata/core/`.
   - **Não tocar** nos arquivos de mídia em `/srv/external3/homeserver/{media,torrents}` (eles permanecerão intactos no HD de 18 TB).
2. Na VM antiga `121 (mediaserver-playback)`:
   - Parar o Jellyfin limpo (`docker compose stop`) e copiar `/srv/appdata/jellyfin` para `/mnt/pve/nvme-secondary/migration-appdata/playback/jellyfin/`.
3. Na VM antiga `111 (homelab-hermes)`:
   - Copiar o estado pareado do WhatsApp e memórias (se desejar preservar sessão) para `/mnt/pve/nvme-secondary/migration-appdata/hermes/`.
4. Desligar de forma limpa as VMs `110`, `111`, `120` e `121` (`qm shutdown <id>`) e remover a VM `122` (`mediaserver-edge`, já aposentada). Desmarcar `onboot=0` nas antigas enquanto ficam de reserva.

## Passo 3 — Provisionamento Declarativo (`OpenTofu` + `Ansible`)

1. Em `homelab-platform/infrastructure/proxmox/`:
   - Copiar `terraform.tfvars.example` para `terraform.tfvars` (gitignored) preenchendo endpoint PVE, chaves SSH, token e IDs dos mappings.
   - Rodar `tofu init && tofu plan && tofu apply`.
   - Conferir que `VM 100 (homelab-hub)` e `VM 200 (homelab-k3s)` subiram em `nvme-secondary`, com firewall PVE ativo e `onboot=1`.
2. Em `homelab-platform/infrastructure/ansible/`:
   - Preencher `inventory/hosts.yml` (gitignored) e os arquivos privados em `/opt/homelab-hub/.env` na `VM 100`.
   - Rodar `ansible-playbook -i inventory/hosts.yml playbooks/hub.yml`:
     - O playbook gera `/srv/hub/authelia/users_database.yml` (`0600`) automaticamente para o usuário `root` a partir de `ROOT_PASSWORD` em `/opt/homelab-hub/.env` (caso ainda não exista) e copia `./authelia/configuration.yml` se ausente/preparado conforme `configuration.yml.example`.
     - Autenticar o Tailscale na `VM 100` (usando o mesmo Tailnet/hostname ou atualizando o IP Tailscale no DNS Cloudflare) e validar Traefik TLS wildcard `*.greis.dev.br`, Authelia e Grafana/Loki.
   - Rodar `ansible-playbook -i inventory/hosts.yml playbooks/k3s.yml`:
     - Conferir `/mnt/storage` (18 TB ext4 montado por UUID), `/mnt/transcode` (disco de scratch 48 GiB), `/dev/dri/renderD128`, `RequiresMountsFor` no `k3s.service`, e `flux-system` com a chave `sops-age`.

## Passo 4 — Restauração de Appdata & Ativação GitOps (`FluxCD`)

1. Na `VM 200 (homelab-k3s)`, garantir as pastas de PVCs/hostPaths:
   - `/mnt/storage/homeserver` (já contém `media/` e `torrents/` intactos com os hardlinks).
   - `/mnt/transcode/jellyfin` (UID/GID `1000:1000`).
2. Fazer `flux bootstrap github` (ou aplicar `clusters/homelab`) para reconciliar `platform` e `spoke-mediaserver` / `spoke-hermes`.
3. Aguardar criação dos PVCs `local-path` de `spoke-mediaserver`, escalar momentaneamente os deployments para `0` réplicas (`kubectl -n spoke-mediaserver scale deploy --all --replicas=0`), copiar os `appdata` preservados (`jellyfin`, `radarr`, `sonarr`, `prowlarr`, `bazarr`, `seerr`, `qbittorrent`) para os respectivos diretórios de PV garantindo `chown -R 1000:1000`, limpar `<BaseUrl>` no `network.xml` do Jellyfin (padronizando acesso direto em `/`) e ajustar URLs internas nos apps que ainda apontavam para `172.28.64.x` (para DNS K8s `http://radarr:7878/radarr`, etc.), restaurando `replicas=1` via `flux reconcile kustomization spoke-mediaserver --with-source` e `flux reconcile kustomization spoke-mediaserver-secrets --with-source`.
   - Conferir nos apps com banco próprio (`Jellyfin`, `Seerr`, `Radarr`, `Sonarr`, `Prowlarr`, `qBittorrent`) se o login `root` restaurado utiliza a mesma `ROOT_PASSWORD` padronizada; no `Bazarr` e no `arr-mcp` UI o `initContainer` já aplica `root` e as API keys automaticamente na subida.
   - Caso não tenha reaproveitado `JELLYFIN_API_KEY` / `SEERR_API_KEY` do `.private-vault/`, gerar novas API keys em `Jellyfin Dashboard -> API Keys` e `Seerr Settings -> General`, atualizar `secrets/mediaserver-secrets.sops.yaml`, commitar e reconciliar `spoke-mediaserver-secrets`.
4. Buildar/carregar a imagem limpa `homeserver-jellyfin-abyss:12.2-2f809171-r6` no `containerd` do K3s (`k3s ctr images import`) a partir de `homelab-mediaserver/docker/jellyfin-abyss/`.

## Passo 5 — Checklist de Aceite e Encerramento do Legado

- [ ] `https://auth.greis.dev.br` e `https://homelab.greis.dev.br` respondem com TLS automático Cloudflare válido e SSO Authelia ativo.
- [ ] `https://grafana.greis.dev.br` exibe métricas de `pve01`, `VM 100`, `VM 200`, discos e logs centralizados no Loki.
- [ ] `https://jellyfin.greis.dev.br/` e `http://<IP-LAN-HUB>:8096/` reproduzem vídeo com tema Abyss, mídia RO e transcode QuickSync `/dev/dri`.
- [ ] qBittorrent confirma os **733 torrents concluídos em seeding** sem baixar tudo de novo (hardlinks `/data` preservados).
- [ ] Hermes (`https://hermes.greis.dev.br` e WhatsApp) consulta biblioteca/alertas e completa pedido + preview + download via `arr-mcp` sem erros.
- [ ] Somente após 100% de aceite: destruir as VMs antigas desligadas (`110`, `111`, `120`, `121`) no NVMe 1, confirmar o agendamento diário de `vzdump` no `nvme-secondary` e descomentar `vaultwarden` em `kubernetes/spokes-registry/kustomization.yaml` para ativar o Spoke #3!
