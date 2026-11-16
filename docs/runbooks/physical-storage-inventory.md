# Inventário físico de storage

Este inventário observa dispositivos e filesystems. Não concede capacidade de
alocação, não readmite aplicações e não substitui o supervisor de storage.
Montagem presente e SMART `passed` não comprovam integridade global do conteúdo.

## Fontes e ownership

- No Proxmox, a lista de discos do nó identifica os dispositivos locais. A lista
  de **Storage** do datacenter identifica datastores cadastrados, que podem ser
  apenas parte dos discos conectados. Não cadastrar nem formatar um disco para
  fazê-lo aparecer no painel.
- O coletor existente consulta somente GET em
  `/nodes/{node}/disks/list?include-partitions=1&skipsmart=1`, com o token RO e
  `Sys.Audit` já existentes. Não há credencial nova nem ampliação de ACL.
- Dispositivo USB entregue exclusivamente ao core é observado dentro desse
  guest. Seu owner permanece `vm-<id>`, separado do owner `host` dos discos PVE.
- O [probe](../../services/telemetry/storage.py) usa metadados de `lsblk` e
  `findmnt`, sem enumerar arquivos ou ler conteúdo de mídia. Só dispositivos
  físicos reconhecidos entram na soma; discos QEMU e partições não são somados.
- A capacidade física é diferente do tamanho do filesystem e de seus bytes
  disponíveis. Um mount NFS é outra visão do mesmo armazenamento, não outro HD.

No host, a API informa partições, tipos e se estão montadas, mas não fornece o
path ou o modo RO/RW desses mounts. Esses campos ficam desconhecidos. A ausência
de uma partição ou de um filesystem montado não torna o dispositivo descartável.
Preservar as origens, o passthrough exclusivo e os mounts já autorizados.

## Coleta no core

A instalação usa o node_exporter já existente, sem novo daemon ou unit:

- Script root 0755: `/usr/local/lib/homelab-telemetry/storage.py`.
- Saída sanitizada: `/var/lib/prometheus/node-exporter/homelab-storage.prom`.
- Cron root: `/etc/cron.d/homelab-storage-inventory`, a cada minuto, com
  `flock -n /run/homelab-storage-inventory.lock` e `timeout 35s`.
- O arquivo `.prom` é substituído atomicamente. Em erro, a saída informa
  `homelab_storage_probe_up 0`; não reaproveita o snapshot anterior como saudável.
- O coletor aceita a observação do probe por até 150 segundos. O seu próprio
  cache expira em 75 segundos, usando tempo monotônico.

SMART ATA usa apenas `-H -j`, transporte explícito e `-n standby,3,5`. Se o disco
está em standby ou o modo de energia não pode ser determinado, a consulta não
prossegue e a saúde fica desconhecida. Não executa self-test, reparo, mudança de
energia nem habilitação de SMART. O terceiro argumento evita a continuação que
seria possível quando a detecção de energia não é suportada.
[Manual do smartmontools](https://github.com/smartmontools/smartmontools/blob/main/src/smartctl.8.in).
No PVE periódico, SMART é inteiramente omitido; um resultado histórico não é
apresentado como atual.

O `.env` privado do controle define `STORAGE_CORE_EXPORTER_URL` como o endpoint
IPv4 RFC1918 do exporter, porta 9100, path `/metrics`, sem credenciais, query ou
redirecionamento; define também `STORAGE_CORE_VMID` para o owner correto.
Ausência dessa configuração aparece como fonte desconhecida. O snapshot interno
fica em `http://pve-metrics:9101/inventory`, somente nas redes privadas existentes.
O portal usa `/api/v1/storage`, sessão humana e `Sys.Audit` para cada nó permitido.
Não publicar a porta do coletor nem encaminhar ticket humano ao exporter.

## Leitura dos sinais

| Sinal | Significado |
|---|---|
| `homelab_storage_source_up` | Fonte atual válida; zero significa indisponível ou expirada |
| `homelab_storage_last_success_timestamp_seconds` | Instante da última observação aceita daquela fonte |
| `homelab_storage_disk_capacity_bytes` | Capacidade física por `scope`, `node`, `device` e `owner` |
| `homelab_storage_disk_health{state=...}` | `passed`, `failed` ou `unknown`, sem inferir saúde por mount |
| `homelab_storage_disk_readonly` | Modo do dispositivo; ausência significa desconhecido |
| `homelab_storage_disk_mounted` | Pelo menos um filesystem observado montado naquele dispositivo |
| `homelab_storage_filesystem_*_bytes` | Tamanho, usado e disponível por mount físico do core |

Modelo, nome lógico de dispositivo e mount publicado são sanitizados. Serial,
UUID, credenciais e inventário bruto não são labels nem campos da API. Os nomes
`sda`/`sdb` podem mudar em um boot: servem para localizar a observação atual, não
para autorizar operações sobre o disco.

Se a fonte falhar, conferir primeiro frescor, estado do cron e
`node_textfile_scrape_error`. Verificar o endpoint privado e permissões da API,
sem transformar ausência de métricas em diagnóstico de corrupção. O inventário
não inicia serviços, não remove `HOLD`, não monta dispositivos e não repara dados.

Para reverter esta extensão, retirar somente o cron de inventário e restaurar
seus arquivos a partir do recibo privado de implantação. Não remover o
node_exporter, o supervisor, seus cron jobs, leases ou configuração de storage.
O inventário expirará para desconhecido. Retirar `STORAGE_CORE_*` do consumidor
não altera mount ou ownership, mas exige recriar apenas o coletor para aplicar
a configuração nova.
