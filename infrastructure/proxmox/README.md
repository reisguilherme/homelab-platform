# Proxmox e máquinas virtuais

Este diretório delimita a futura implementação da infraestrutura. Ainda não
contém instalador nem configuração aplicada. O [to-be](../../docs/architecture/to-be.md)
define as VMs de entrada, playback e núcleo privado, com administração fora da
rede pública.

A plataforma será responsável por criar/excluir VMs, alterar CPU/RAM/discos,
atribuir usuários e ACL por VM, aplicar regras de rede e publicar recursos de
storage. A aplicação poderá operar seus serviços com identidade restrita;
receber métricas ou um volume não concede administração do Proxmox.

## Antes da implantação

O [roteiro de instalação assistida](../../docs/runbooks/proxmox-installation-handoff.md)
prepara a passagem física e a reconexão por Ethernet/SSH. Ainda não libera
apagar o Ubuntu nem contém os valores privados do host.

- Os dois SSDs já estão identificados no inventário privado. Confrontar
  modelo/serial do candidato no instalador e obter autorização de sobrescrita
  do dispositivo/escopo exatos após fechar a preservação. A autorização geral
  para refatorar não autoriza apagar o sistema.
- Usar a ISO x86_64/amd64 para o processador Intel; a imagem ARM64 não serve
  para este host. O arquivo local já teve seu SHA-256 conferido conforme o
  roteiro. A gravação do pendrive e o teste de boot ainda não foram verificados.
- Aproveitar o checkpoint de mídia restaurado e o ensaio de inicialização
  isolada já registrado, com seus limites. A captura final, incluindo o outro
  projeto e os sete volumes, foi selada. Os 22 containers antes ativos seguem
  parados; concluir e verificar a cópia Windows e a restauração do novo conjunto.
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
