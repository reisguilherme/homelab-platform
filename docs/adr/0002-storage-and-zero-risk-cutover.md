# ADR-0002: Storage Direto, Eliminação de Leases de 45s e Cutover Sem Risco

- **Status:** Aceito
- **Contexto:** Anteriormente, o HD USB de 18 TB era entregue à VM `mediaserver-core` e re-exportado via NFSv4.2 para a VM `mediaserver-playback` no mesmo host, protegido por um script em `crontab` (`storage_supervisor.py`) com leases de 45 segundos que matava containers (`exit 78`, `restart: 'no'`) após qualquer atraso de cron ou reboot. Além disso, o `local-lvm` do NVMe 1 estava saturado (~4,8 GiB livres) devido às 4 VMs antigas.

## Decisão

1. **Passthrough Direto do HD de 18 TB e da iGPU para a `VM 200 (homelab-k3s)`:**
   - Como todos os Spokes rodam na `VM 200`, elimina-se o loop NFS entre VMs no mesmo notebook.
   - O HD USB 18 TB (`ext4`) é montado por UUID em `/mnt/storage` e o serviço `k3s.service` recebe `RequiresMountsFor=/mnt/storage /mnt/transcode` via drop-in systemd, substituindo completamente o watchdog de 45 segundos.
   - Dentro do K3s, `radarr`, `sonarr`, `qbittorrent` e `bazarr` montam `/mnt/storage/homeserver` em `/data` (RW, preservando hardlinks atômicos e os 733 torrents em seeding), enquanto o Jellyfin monta `/mnt/storage/homeserver/media` em `/data/media` com `readOnly: true` e recebe `/dev/dri` (Intel UHD QuickSync).
2. **Liberação do 2º NVMe (`nvme-secondary`, 512 GB) para Cutover Zero-Risco:**
   - Com a consolidação anterior do acervo concluída, o 2º SSD NVMe é inicializado no Proxmox como datastore `nvme-secondary` (diretório/LVM-thin com suporte a `images` e `backup`).
   - Os discos das novas VMs `100` (`homelab-hub`) e `200` (`homelab-k3s`) e os backups consistentes dos `appdata` são criados no `nvme-secondary`, permitindo manter as VMs antigas (`110`, `111`, `120`, `121`) **intactas e apenas desligadas** no NVMe 1 durante toda a janela de cutover como rollback instantâneo.
   - Após validação completa da nova arquitetura em produção, as VMs antigas são removidas e o `nvme-secondary` assume a rotina diária de backups `vzdump` + disco de scratch/transcode.

## Consequências

- Fim dos travamentos por NFS loopback, OOMs de 192 MiB e paradas permanentes por expiração de lease de 45s.
- Transcode em hardware via Intel QuickSync sem custo de licença nem passthrough de dGPU.
- Rollback imediato durante a virada simplesmente desligando as VMs `100`/`200` e ligando `110`/`120`/`121`.
