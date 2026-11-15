# Proxmox e máquinas virtuais

Este diretório delimita a implementação da infraestrutura. O proprietário
instalou Proxmox no SSD autorizado; identidade e acesso privado SSH/HTTPS foram
verificados. Core, playback e edge já executam Ubuntu 24.04, com rede privada
e acesso por SSH ProxyJump. Não há instalador automatizado do hypervisor; o
[gerador](../../scripts/proxmox_bootstrap.py) produz somente um bundle offline
para revisão, usando um [perfil privado derivado do exemplo](profile.example.json).
O [to-be](../../docs/architecture/to-be.md)
define as VMs de entrada, playback e núcleo privado, com administração fora da
rede pública.

A plataforma será responsável por criar/excluir VMs, alterar CPU/RAM/discos,
atribuir usuários e ACL por VM, aplicar regras de rede e publicar recursos de
storage. A aplicação poderá operar seus serviços com identidade restrita;
receber métricas ou um volume não concede administração do Proxmox.

## Host entregue e próximos passos

O [roteiro de instalação assistida](../../docs/runbooks/proxmox-installation-handoff.md)
registra a passagem física e a reconexão concluídas. As três VMs usam 11 GiB
de RAM e discos virtuais de 160/80/16 GiB; o segundo SSD ext4 continua
desmontado. Após o bootstrap, o proprietário autorizou o HD de 18 TB
exclusivamente no core, com inspeção RO antes de RW e preservação do conteúdo.
A bridge privada tem NAT sem DNAT; o firewall legado está ativo
para os guests e `enable: 0` no host preserva a gestão LAN como gap.
O [runbook dos convidados](../../docs/runbooks/proxmox-guests.md) explica
geração, preflight, aplicação e testes. O
[estado atual](../../docs/implementation-status.md#vms-e-rede-privada)
registra as provas TCP/pacotes e de reboot, com seus limites. Autostart ordenado,
acesso e filtros persistiram após reboot. A
[etapa de storage](../../docs/runbooks/storage-core-handoff.md) aplicou
passthrough somente do dispositivo USB e NFS RO para playback; não há apps,
Docker ou GPU nos convidados.
Os valores privados permanecem fora deste repositório.

- Os dois SSDs já estão identificados no inventário privado. Confrontar
  modelo/serial antes de futuras operações de disco. Preservar o segundo
  SSD e todos os discos USB; a autorização de instalação não os inclui.
  A autorização posterior do HD de 18 TB limita-se ao passthrough, inspeção,
  mount preservado e exportação, sem formatação ou reparo automático.
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
- Preservar as provas TCP/pacotes e de reboot concluídas; testar gestão
  restrita e os fluxos reais das aplicações antes de expor playback. Portas
  testadas com listeners temporários não comprovam NFS RO nem autenticação.
  Manter acesso administrativo quando o core estiver indisponível.
- Preservar o passthrough e a prova NFS RO já aplicados; ensaiar perda/retorno
  do disco e coordenação com as pausas da aplicação. Não executar dois
  recuperadores concorrentes.

O hub é uma dependência compartilhada. Expandir compute não replica o HD e não
produz alta disponibilidade de dados. Leia também
[energia e recuperação](../../docs/architecture/power-recovery.md) e
[operação e governança](../../docs/architecture/operations.md).
