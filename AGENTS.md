# Homelab Platform — guia do agente

Este repositório é a fonte da arquitetura geral, contratos de integração e
configuração da infraestrutura compartilhada. Aplicações vivem em repositórios
próprios; o catálogo aponta para commits imutáveis e distingue proposta de execução.

## Limites

- Não fazer deploy, reiniciar o servidor, formatar/particionar discos ou alterar
  montagens sem a autorização operacional correspondente. Publicar código não
  autoriza aplicar a configuração. O proprietário autorizou indisponibilidade
  em 15/11/2026; isso não autoriza sobrescrever o SSD candidato já identificado
  nem dispensa o estado final preservado e verificado. A inicialização da mídia
  em clones foi examinada; isso não comprova integração completa ou produção.
  A captura final foi selada, com 22 containers mantidos parados e SSH disponível;
  a segunda cópia e restauração ainda precisam de aceite. Consulte o estado de implementação.
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
