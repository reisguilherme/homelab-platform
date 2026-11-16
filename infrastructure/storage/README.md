# Hub de arquivos inicial

O [runbook](../../docs/runbooks/storage-core-handoff.md) registra a passagem do
HD ao core e os testes reais. Estes arquivos são referências para revisão;
não são um instalador nem devem sobrescrever arquivos do sistema.

| Arquivo | Destino dentro do guest |
|---|---|
| [core.fstab.example](core.fstab.example) | Acrescentar somente a linha autorizada ao `fstab` do core |
| [playback.fstab.example](playback.fstab.example) | Acrescentar somente a linha NFS ao `fstab` da playback |
| [nfs.conf.example](nfs.conf.example) | `/etc/nfs.conf.d/90-homelab.conf` no core |
| [media.exports.example](media.exports.example) | `/etc/exports.d/homelab-media.exports` no core |
| [nfs-server.storage.conf](nfs-server.storage.conf) | Drop-in da unit existente `nfs-server.service`, somente no core |
| [docker-playback.storage.conf](docker-playback.storage.conf) | Drop-in da unit existente `docker.service`, somente na VM playback dedicada |

Substituir o UUID e os endereços de documentação `192.0.2.0/24` por valores do
perfil privado conferido. Preservar todas as entradas existentes. O core monta
por UUID, sem fsck automático; a playback mantém `noauto`, com dependência
explícita do Docker para solicitar o mount. Nenhum arquivo vai ao PVE.

O export contém apenas a árvore de mídia, sem backup, staging, downloads ou
appdata. `fsid=0` faz essa árvore aparecer como `CORE:/`. `all_squash` mapeia
operações para UID/GID 1000 e `ro` impede escrita no servidor, mesmo quando um
cliente pede RW. `subtree_check` é explícito porque o backup compartilha o
filesystem fora do subdiretório exportado; renames podem produzir handles
obsoletos, a validar com as aplicações. Não adicionar `crossmnt`, `insecure`
ou exports abrangentes. [Opções de export](https://man7.org/linux/man-pages/man5/exports.5.html).

`mountpoint` verifica presença da montagem, não identidade ou saúde. O drop-in
vincula o NFS ao mount configurado por UUID; consumidores ainda precisam dos
próprios guards. Confirmar dependências efetivas após `daemon-reload`, versões
em `/proc/fs/nfsd/versions`, exports e listeners. O `rpc.mountd` do pacote pode
manter listeners auxiliares: o firewall deve continuar negando essas portas.
[Configuração NFS](https://manpages.ubuntu.com/manpages/noble/man5/nfs.conf.5.html).

Na playback, `RequiresMountsFor=/srv/media-view/media` solicita a montagem
mesmo com `noauto`. `BindsTo` e `After` apontam para a unit escapada
`srv-media\x2dview-media.mount`: o Docker depende de ela estar ativa. Isso
vincula todo o daemon ao mount, sendo adequado somente a esta VM dedicada,
sem substituir os guards de identidade e inicialização do consumidor.
[Dependências de mounts no systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html#RequiresMountsFor=).

O drop-in foi relido no guest, suas dependências efetivas foram conferidas e
`systemd-analyze verify` passou incluindo explicitamente a unit de mount
gerada. O restart do Docker ainda sem containers passou; depois da restauração,
o reboot da VM playback também passou, com mudança de boot ID e retorno
automático do NFS RO, Docker e Jellyfin saudável. A integração e os limites
do aceite da aplicação estão no [runbook de playback](https://github.com/reisguilherme/homelab-mediaserver/blob/2ac092cdb3f6e57e26505fc123f13f21d87cf141/docs/runbooks/playback-nfs.md).

O retorno automático após queda da fonte USB ainda não está aceito. NFS `hard`
pode bloquear I/O quando o servidor desaparece; não contornar com `soft`,
desmontagem forçada/lazy ou retomada de scans sobre uma biblioteca ausente.

## Detecção e contenção por autorização temporária

[storage_supervisor.py](../../scripts/storage_supervisor.py) coordena o primeiro
estágio de proteção via QGA existente. [guest-storage-probe.py](guest-storage-probe.py)
tem somente duas responsabilidades: observar o HD no core e publicar autorização
temporária no SSD da playback. O [plano](../../docs/plans/2026-11-15-storage-containment.md)
delimita essa entrega. A existência desses arquivos/testes não comprova deploy.

Não há start/stop de VM ou container, remount, alteração de export/passthrough,
fsck, escrita no acervo ou scan. O consumidor deve recusar inicialização e
conter sua aplicação quando a autorização faltar/vencer. **Sem esse guard,
instalar apenas o supervisor não contém o Jellyfin.**

O core exige UUID único, serial informado por lsblk e serial ATA, tamanhos, partição, ext4 RW,
ausência de erros ext4, geração USB e mount correto. Lê uma fixture de 64 KiB
com O_DIRECT e hash conhecido, fora da árvore de mídia exportada. Se a bridge,
kernel ou filesystem não suportar a leitura direta, a autorização fica fechada;
não há fallback para leitura potencialmente atendida pelo cache.

### Perfis e preparação privada

Todos os caminhos abaixo são destinos de instalação, não comandos automáticos.
Copiar/revisar arquivos exige a autorização operacional correspondente. Não
colocar perfis reais, estados, lease journals ou conteúdo de fixtures no Git.

| Local | Preparação |
|---|---|
| PVE | Script em `/usr/local/lib/homelab-storage/storage_supervisor.py`, root 0755; perfil `/etc/homelab-storage-supervisor.json`, root 0600; diretório `/var/lib/homelab-storage-supervisor`, root 0700 |
| Core e playback | Helper em `/usr/local/lib/homelab-storage/guest-storage-probe.py`, root 0755; perfil `/etc/homelab-storage.json`, root 0600; diretório `/var/lib/homelab-storage`, root 0700 |
| Playback | Subdiretório `/var/lib/homelab-storage/admission`, root 0755; consumidor monta esse diretório RO e lê `lease` root 0644, mais boot ID real do guest |
| Core | `/srv/external3/.homelab-storage/health.bin`, arquivo regular de exatamente 65536 bytes, root-owned, sem hardlinks/symlinks/escrita de grupo ou outros; hash registrado no perfil SSD |

Criar a fixture somente depois de confirmar mount, dispositivo e autorização.
Nunca criar sua pasta se o mount estiver ausente. A criação não faz parte do
helper. A árvore da fixture e os arquivos de configuração exigem ancestrais
root-owned sem escrita de grupo/outros; conferir isso no volume existente,
sem alterar permissões recursivamente sobre o acervo para satisfazer um check.

Schema privado do PVE, exemplo fictício:

```json
{"version":1,"core_vmid":900,"playback_vmid":901,"core_name":"storage-core","playback_name":"media-playback","usb_port":"1-2"}
```

O supervisor confere nomes, ausência de lock operacional e `usb0` do core antes
dos comandos. Não move dispositivo para outra porta. Perfil do core exige
exatamente `version: 1`, `role: "core"`, `filesystem_uuid`, `bridge_serial`
(serial informado por lsblk, que pode ser ATA conforme o driver), `ata_serial`
(smartctl), `disk_size_bytes`, `partition_size_bytes`, `partition_number`,
`fixture_sha256` e `smart_device_type`. Este último aceita somente `sat,12` ou
`sat,16`, conforme leitura comprovada na bridge; não há autodetecção ou fallback.
O inventário lsblk usa `--tree` explicitamente para preservar a relação disco/partição.
Perfil da playback:
`{"version":1,"role":"playback"}`. Parâmetros físicos exigem inspeção privada;
não usar os valores do exemplo em produção.

### Operação e agendamento

Executar no PVE, como root, depois de revisar ambos os helpers e o guard:

```sh
python3 -B /usr/local/lib/homelab-storage/storage_supervisor.py status
python3 -B /usr/local/lib/homelab-storage/storage_supervisor.py arm
python3 -B /usr/local/lib/homelab-storage/storage_supervisor.py watch --seconds 58
```

`arm` só vale para a primeira ativação. O script começa em HOLD e só publica
`ready` após probe fresco. Um processo guest pendente conserva PID/nonce e impede
outro probe. Deadline do probe: 15 s; cada chamada `qm`: até 8 s. Um tick não
espera I/O do HD: lança operação assíncrona ou consulta status. `watch` libera
o lock entre ticks de 2 s e mantém intervalo mínimo de 10 s entre probes.

Depois do aceite sintético, o cron **já existente e ativo** no PVE pode chamar
`watch --seconds 58` a cada minuto. Não instalar outra unit/daemon. Sobreposição
de invocações encontra flock e não duplica operações. Não gravar um log infinito
no SSD; usar o estado sanitizado do comando `status` até integrar alertas e
retenção à observabilidade. Esta entrega não instala monitoramento ou alertas.

A janela de 58 s deixa margem para o custo dos processos `qm` antes do poll e
reduz a lacuna entre invocações. O tick em andamento pode ultrapassar o fim da
janela; seu lock ainda evita sobreposição de efeitos. Deadlines de 15 s e lease
de 45 s continuam iguais. A primeira ativação exige cron confirmado ativo e
observação da passagem entre minutos: manter `watch --seconds 58` até essa
passagem se necessário. Não encerrar um watch curto arbitrário deixando probe
pendente e aguardar o primeiro cron; esse intervalo pode produzir HOLD mesmo
com HD saudável. Testes de cadência incluem tempo gasto em cada chamada `qm`.

A autorização dura no máximo 45 s, usa boot ID e uptime locais da playback e
tem cinco linhas no formato especificado no plano. Sequência persistida antes
da publicação bloqueia replay de comandos. O prazo UTC recebido limita comandos
atrasados; NTP funcional e relógios coerentes são precondições. Atraso de cron,
perda do coordenador ou falha de publicação deixam a autorização vencer.
Isso contém por prazo, mas não promete encerrar processos em D-state.

```sh
python3 -B /usr/local/lib/homelab-storage/storage_supervisor.py hold
python3 -B /usr/local/lib/homelab-storage/storage_supervisor.py resume
```

`hold` é a intenção administrativa persistente. Depois de resolver a causa,
`resume` pede uma prova nova e não executa start. Quando uma nova autorização
chegar, `restart: unless-stopped` pode reiniciar o container que o guard encerrou.
Assim, `resume` é uma decisão explícita de readmissão, com possível retorno do
Jellyfin. Um `docker compose stop` manual permanece respeitado pelo Docker; se o
operador quiser reativá-lo, precisa iniciá-lo explicitamente. `resume`
recusa execuções pendentes e não apaga PID desconhecido. Timeout durante um
lançamento QGA pode ter deixado um processo real sem PID recebido: diagnosticar
via console/QGA e evidência privada, sem limpar o estado para contornar a dúvida.
Mudança de boot PVE ou perfil também exige revisão do estado, mantendo fechado.

`arm`, `resume` ou `hold` retornam **75** quando o lock está ocupado, com
`{"mode":"busy"}`: a ação **não foi aplicada**. Repetir de forma limitada após
pequena espera e confirmar o resultado pelo JSON e por `status`; nunca tratar
apenas o término do processo como confirmação. Para `arm`/`resume`, conferir
`mode: armed` e depois `reason: healthy-lease-published`. Para `hold`, conferir
`mode: hold` e a autorização fechada na playback. `busy` em `status` ou `watch`
é contenção normal de concorrência, não prova de saúde nem de ação aplicada.

Os testes Linux cobrem identidade, geração, atraso, nonce, PID pendente, intenção
manual, lease e leitura direta em fixture. O ensaio seguinte é expiração sintética
da autorização, sem desligar HD ou retirar export vivo. A reintegração física,
reconciliação de escritas e recuperação NFSv4 continuam etapas posteriores.
