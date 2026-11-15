# Entrega do HD ao core

O proprietário reconectou e autorizou o HD de 18 TB identificado na ficha
privada: posse exclusiva pelo core, inspeção inicial somente leitura e montagem
para escrita após conferência, preservando acervo e backup. Sem formatação,
particionamento, reparo automático ou alteração dos outros discos.

1. Conferir serial, capacidade, UUID/PARTUUID, SMART, topologia USB e ausência
   de montagens/posse concorrente. Preservar a Ethernet USB.
2. Passar somente o dispositivo USB por porta dedicada ao core; conferir
   novamente sua identidade dentro do guest, sem automount ou consumidores.
3. Montar `ro,noload` para conferir layout e recibo do backup. O marcador
   `needs_recovery` após retirada sem unmount não prova corrupção. Erros de
   journal, ext4 ou I/O impedem avançar; não executar fsck corretivo.
4. Desmontar e montar novamente para escrita, sem `noload`, permitindo apenas
   o replay normal do journal. Conferir logs e identidade; nenhuma aplicação,
   scan ou export deve iniciar por consequência dessa operação.
5. Registrar evidências privadas, estado e limites públicos. A passagem do HD
   não implementa por si só NFS, restauração, recuperação USB ou playback RO.

Os paths e proprietários existentes serão preservados. Uma futura entrada de
mount não habilitará fsck automático. Não montar simultaneamente em host e guest,
não usar desmontagem forçada/lazy, não restaurar o recuperador legado antes de
adaptar a coordenação host/core/consumidores.

## Execução e extensão ao hub

Passagem concluída em 15/11: identidade física e filesystem conferidos, SMART
sem os alertas examinados, leitura inicial `ro,noload` e montagem RW fresca.
O kernel registrou recuperação normal do journal concluída, sem erros de I/O
ou ext4. Recibo e 21 metadados do backup tiveram hashes conferidos; os cinco
arquivos tar tiveram tamanhos conferidos, sem nova leitura integral dos hashes.

O hub aprovado no to-be também recebeu NFSv4.1/4.2, somente mídia e somente
playback, com export RO. Quatro operações sobre fixture própria foram negadas
com EROFS mesmo usando cliente RW. A leitura da fixture por UID 1000 passou;
uma amostra de 64 KiB de mídia real coincidiu entre core e playback. Isso não
verifica o arquivo inteiro, catálogo ou reprodução. A fixture foi removida.

Decisão de implementação: o gerador instalado não produziu dependência de
mount. Um drop-in da unit NFS existente **dentro do core** explicita
`RequiresMountsFor`, `BindsTo`, `After` e condição de mount. Não houve nova
unit ou alteração de fstab no Proxmox. As entradas originais de fstab dos
guests foram preservadas; somente as linhas necessárias foram acrescentadas.

Após reboot do core, o HD montou automaticamente por UUID e o NFS iniciou,
com zero units em falha, sem erros de storage e recibo preservado. A playback
foi desmontada antes e remontada manualmente depois; a leitura de mídia foi
repetida. `noauto` continua no cliente. Esse teste não comprova recuperação
automática de perda de energia/USB, nem autoriza iniciar scans/aplicações.

Os [exemplos](../../infrastructure/storage/README.md) e o
[runbook](../runbooks/storage-core-handoff.md) preservam configuração e alcance.
