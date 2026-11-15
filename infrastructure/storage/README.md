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

Substituir o UUID e os endereços de documentação `192.0.2.0/24` por valores do
perfil privado conferido. Preservar todas as entradas existentes. O core monta
por UUID, sem fsck automático; a playback mantém `noauto` até aceitar os guards
de inicialização/ausência de mídia das aplicações. Nenhum arquivo vai ao PVE.

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

O retorno automático após queda da fonte USB ainda não está aceito. NFS `hard`
pode bloquear I/O quando o servidor desaparece; não contornar com `soft`,
desmontagem forçada/lazy ou retomada de scans sobre uma biblioteca ausente.
