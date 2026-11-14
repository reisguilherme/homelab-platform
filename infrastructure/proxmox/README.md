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

- Inventariar os dois SSDs e confirmar o dispositivo e o escopo exatos de qualquer
  sobrescrita. A autorização geral para refatorar não identifica esse dispositivo.
- Concluir a reconciliação do acervo e produzir/restaurar o conjunto consistente
  de bancos, configuração e estado, em destinos independentes.
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
