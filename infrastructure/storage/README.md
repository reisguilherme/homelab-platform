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
