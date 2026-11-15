# Proxmox e máquinas virtuais

Este diretório delimita a implementação da infraestrutura. O proprietário
instalou Proxmox no SSD autorizado; identidade e acesso privado SSH/HTTPS foram
verificados. Não há instalador automatizado neste repositório. O [to-be](../../docs/architecture/to-be.md)
define as VMs de entrada, playback e núcleo privado, com administração fora da
rede pública.

A plataforma será responsável por criar/excluir VMs, alterar CPU/RAM/discos,
atribuir usuários e ACL por VM, aplicar regras de rede e publicar recursos de
storage. A aplicação poderá operar seus serviços com identidade restrita;
receber métricas ou um volume não concede administração do Proxmox.

## Host entregue e próximos passos

O [roteiro de instalação assistida](../../docs/runbooks/proxmox-installation-handoff.md)
registra a passagem física e a reconexão concluídas. O host possui zero VMs,
segundo SSD ext4 desmontado e HDs USB desconectados. O firewall está sem regras
configuradas; a entrega do host não comprova isolamento. O
[estado atual](../../docs/implementation-status.md#host-proxmox-entregue)
registra o inventário, versões, capacidade e validação de identidade. Os valores
privados permanecem fora deste repositório.

- Os dois SSDs já estão identificados no inventário privado. Confrontar
  modelo/serial antes de futuras operações de disco. Preservar o segundo
  SSD e todos os discos USB; a autorização não inclui esses dispositivos.
- A instalação usou a arquitetura x86_64/amd64 para o processador Intel; a
  ISO local teve seu SHA-256 conferido conforme o roteiro. ARM64 não serve
  para este host; não há instalação adicional pendente nesta fase.
- Aproveitar o checkpoint de mídia restaurado e o ensaio de inicialização
  isolada já registrado, com seus limites. A captura final, incluindo o outro
  projeto e os sete volumes, foi selada, com os 22 containers antes ativos
  parados. O proprietário decidiu prosseguir com o backup final completo e
  checksums conferidos somente no HD de 18 TB. A transferência Windows foi
  interrompida, incompleta, e não é origem de restauração; novo ensaio integral
  do conjunto final não é pré-requisito da instalação. O checkpoint anterior
  permanece preservado, e o risco de cópia única do estado final continua.
  A reconciliação do acervo e o reparo continuam no projeto consumidor; não
  reativar workers históricos inativos apenas para completar a instalação.
- Medir RAM disponível e consumo sob carga. O orçamento nominal do desenho deve
  ser ajustado à memória utilizável, ao cache e ao pico de transcode.
- Provar bridges/firewall, acesso privado ao console e rollback antes de expor
  o playback. Manter acesso administrativo quando o core estiver indisponível.
- Ensaiar USB passthrough, perda/retorno do disco, NFS e coordenação com as
  pausas da aplicação. Não executar dois recuperadores concorrentes.

O hub é uma dependência compartilhada. Expandir compute não replica o HD e não
produz alta disponibilidade de dados. Leia também
[energia e recuperação](../../docs/architecture/power-recovery.md) e
[operação e governança](../../docs/architecture/operations.md).
