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
  autorizado; identidade do host e acesso SSH/HTTPS foram conferidos. Core,
  playback e edge já executam Ubuntu com QGA/SSH/NTP. Docker e a imagem
  Jellyfin 12.2 foram instalados na playback; não há GPU nos convidados.
  O proprietário autorizou depois a entrega exclusiva do HD de 18 TB ao core,
  com inspeção RO antes de RW. O passthrough do dispositivo e o NFS RO para
  playback foram aplicados, preservando o adaptador Ethernet USB e o acervo.
  Seguir o [runbook de storage](docs/runbooks/storage-core-handoff.md).
  A rede privada tem NAT sem DNAT e filtros testados;
  autostart ordenado, acesso e filtros persistiram após reboot. A restrição
  da gestão na LAN continua pendente.
  Confira o [estado de implementação](docs/implementation-status.md#vms-e-rede-privada).
  A inicialização da mídia
  em clones foi examinada; isso não comprova integração completa ou produção.
  A captura final foi selada, então com 22 containers parados e SSH disponível;
  seus checksums no HD de 18 TB foram conferidos. O proprietário escolheu
  manter ali a única cópia final completa e prosseguir; a transferência Windows
  foi interrompida e seus parciais não servem para restauração. Não reexigir
  segunda cópia ou novo ensaio integral como condição para instalar. O
  checkpoint anterior permanece intacto. Configuração e cache do Jellyfin
  foram restaurados e conferidos separadamente no core e na playback; isso
  não restaura toda a stack. O Compose independente do consumidor exige mídia
  NFS RO e mantém a automação privada parada. Jellyfin iniciou saudável; API
  autenticada, preservação do catálogo, leitura HTTP e decodificação por CPU
  passaram. Reboot da playback confirmou retorno automático do NFS RO,
  Docker e Jellyfin, preservando catálogo e contenção de scans. Login
  interativo e reprodução em cliente externo não foram testados, conforme
  [Jellyfin na playback](docs/implementation-status.md#jellyfin-na-playback).
  Depois desse aceite inicial, o proprietário autorizou o disco virtual novo
  de 32 GiB para transcode ext4, montado por UUID na playback. O guard exige
  identidade e subpasta RW, com marcador RO; mídia continua RO e o container
  mantém 3 GiB de RAM. Encode curto por CPU e 18 logins/logouts após redefinição
  de senha passaram. A relação de credenciais fica somente no Windows privado.
  Abyss permanece adiado; inspeção da iGPU foi somente leitura, sem passthrough.
  A lease obrigatória de até 45 segundos está implantada; expiração, HOLD e
  preservação de parada manual foram testados. `resume` exige prova nova;
  readmissão pode permitir restart por `unless-stopped`, preservando parada
  manual via Docker. Reboot com SSD/lease passou, recusando a lease anterior; após reboot
  do Proxmox, auditar o estado antes de readmitir. Não prometer retorno integral
  desassistido.
  Recuperação USB e publicação continuam pendentes. A prova NFS RO não
  comprova integridade global do acervo.
  A etapa seguinte criou `homelab-control` com 2 vCPU, 2 GiB e disco virtual
  novo de 24 GiB; o core passou a 4 GiB após medição e parada limpa, mantendo
  11 GiB totais de guests. Chave SSH, HD/NFS, recibo e catálogo foram
  preservados no retorno. QGA/SSH, regras de rede e nginx TLS do controle
  estão operantes; exporters de nó estão nos quatro convidados. API, portal,
  Prometheus e Grafana foram implantados. CRUD, recursos, ACL, idempotência,
  negações de acesso e TOTP passaram em ensaio real descartável. Seis targets
  estão ativos; 22 painéis foram provisionados. Falha e recuperação de coletor
  e exporter dispararam e resolveram os alertas locais. Reboot do controle
  preservou estado e coleta, invalidando a sessão anterior; seu autostart usa
  ordem 5, antes da mídia. Portal e Grafana passaram no navegador real em
  desktop/mobile, com leitura sem mutações. Shutdown/reboot ACPI pelo portal
  não foi ensaiado na VM descartável sem SO. SQLite não tem poda automática.
  Seguir o [runbook de governança](docs/runbooks/platform-governance.md),
  distinguindo credencial de leitura das sessões humanas. Não tratar UI
  sintética, HTTPS ativo ou resposta 202 como operação concluída no Proxmox.
  Criação inicial pelo portal é hardware desligado e sem NIC. O lock do
  portal não coordena alterações externas pelo console; energia, exclusão
  e ACL conservam janela entre revalidação e uso.
- Dispositivos e escopo exatos precisam de autorização antes de alteração
  destrutiva. Preservar o acervo, origens e pausas manuais; não limpar mídia.
- Não substituir fstab inteiro, ativar RTX, reescrever serviço Lenovo, abrir
  portas do roteador ou publicar administração qBit na internet.
- Não criar CI/CD, releases próprias, gerenciador de backups ou units do host.
  Os drop-ins das units NFS no core e Docker na playback pertencem aos guests;
  não instalar o drop-in Docker em host compartilhado ou no Proxmox.
- Nunca versionar .env real, inventário bruto, bancos, tokens, mídia ou evidências
  privadas. Segredos ficam no .env privado de cada implantação, sem *_FILE.
- Usar fixtures temporárias e Python 3.12/Linux para os checks. Teste local não
  prova hardware, storage, isolamento de VMs ou recuperação em produção.
- `scripts/proxmox_bootstrap.py` somente gera bundle ou valida um snapshot
  separado; não faz deploy nem coleta inventário. Seguir o
  [runbook de guests](docs/runbooks/proxmox-guests.md), preservar `vmbr0` e
  não reaplicar o bootstrap sobre IDs/bridge existentes. Valores reais ficam
  privados. Publicação permanece fechada até os aceites de apps, autenticação
  e falha/retorno dos mounts; preservar o NFS RO já testado. Não interpretar
  a liberação de uma porta como esses aceites.

## Fronteiras

Plataforma gerencia Proxmox, recursos de VMs, rede, storage físico/exports,
observabilidade compartilhada e contratos. K3s é evolução futura documentada.
Cada consumidor gerencia aplicação, dados lógicos, exportação de métricas e
procedimentos próprios de parada/readiness/retomada. Uma autoridade coordena cada
incidente de storage; não duplicar automações de recuperação independentes.

Validar contrato não concede acesso, reserva capacidade ou comprova implantação.
A aplicação recebe somente as permissões efetivamente concedidas pela plataforma.
Confira README e docs atuais antes de adaptar material histórico.
