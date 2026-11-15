# Homelab Platform — guia do agente

Este repositório é a fonte da arquitetura geral, contratos de integração e
configuração da infraestrutura compartilhada. Aplicações vivem em repositórios
próprios; o catálogo aponta para commits imutáveis e distingue proposta de execução.

## Limites

- Não fazer deploy, reiniciar o servidor, formatar/particionar discos ou alterar
  montagens sem a autorização operacional correspondente. Publicar código não
  autoriza aplicar a configuração. O proprietário autorizou indisponibilidade
  em 15/11/2026 e, depois, o desligamento limpo e a sobrescrita somente do SSD
  de sistema identificado na ficha privada para instalar Proxmox. Preservar o
  segundo SSD e todos os discos USB. O proprietário instalou Proxmox no SSD
  autorizado; identidade do host e acesso SSH/HTTPS foram conferidos. Não há
  VMs, storage de mídia montado ou isolamento aplicado nesta etapa. Confira o
  [estado de implementação](docs/implementation-status.md#host-proxmox-entregue).
  A inicialização da mídia
  em clones foi examinada; isso não comprova integração completa ou produção.
  A captura final foi selada, então com 22 containers parados e SSH disponível;
  seus checksums no HD de 18 TB foram conferidos. O proprietário escolheu
  manter ali a única cópia final completa e prosseguir; a transferência Windows
  foi interrompida e seus parciais não servem para restauração. Não reexigir
  segunda cópia ou novo ensaio integral como condição para instalar. O
  checkpoint anterior permanece intacto. Restauração, mounts, VMs e isolamento
  continuam pendentes; a entrega do host não comprova essas etapas.
- Dispositivos e escopo exatos precisam de autorização antes de alteração
  destrutiva. Preservar o acervo, origens e pausas manuais; não limpar mídia.
- Não substituir fstab inteiro, ativar RTX, reescrever serviço Lenovo, abrir
  portas do roteador ou publicar administração qBit na internet.
- Não criar CI/CD, releases próprias, gerenciador de backups ou units do host.
- Nunca versionar .env real, inventário bruto, bancos, tokens, mídia ou evidências
  privadas. Segredos ficam no .env privado de cada implantação, sem *_FILE.
- Usar fixtures temporárias e Python 3.12/Linux para os checks. Teste local não
  prova hardware, storage, isolamento de VMs ou recuperação em produção.

## Fronteiras

Plataforma gerencia Proxmox, recursos de VMs, rede, storage físico/exports,
observabilidade compartilhada e contratos. K3s é evolução futura documentada.
Cada consumidor gerencia aplicação, dados lógicos, exportação de métricas e
procedimentos próprios de parada/readiness/retomada. Uma autoridade coordena cada
incidente de storage; não duplicar automações de recuperação independentes.

Validar contrato não concede acesso, reserva capacidade ou comprova implantação.
A aplicação recebe somente as permissões efetivamente concedidas pela plataforma.
Confira README e docs atuais antes de adaptar material histórico.
