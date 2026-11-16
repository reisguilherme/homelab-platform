# Homelab Platform — guia do agente

## Atualização operacional — Órbita, 16/11/2026

O proprietário mantém a conta Proxmox no portal. Os administradores dos oito
aplicativos foram padronizados pela solicitação privada; não alterar usuários
comuns Jellyfin, contas SSH ou senhas Proxmox. A documentação de acesso e os
recibos de autenticação ficam fora do Git. Os processos nativos do core citados
abaixo executam dentro dos containers `homeserver-core-active`; a API de mídia
permanece parada e gateway/worker continuam em manutenção.

O portal Órbita usa o QGA existente para listar/controlar serviços de um catálogo
root-owned, preservando guards de storage e auditoria/idempotência. O browser
nunca envia comandos shell. Disco físico, storage Proxmox e filesystem são
conceitos separados: quatro discos pertencem ao host e o de 18 TB ao core.
Não cadastrar as origens preservadas como novos datastores nem alterar mounts
para fazê-las aparecer no painel. Consulte os runbooks de console operacional e
inventário físico antes de mudar esses fluxos.

Exceção de acesso autorizada posteriormente: Jellyfin também atende a LAN em
`http://192.168.1.20:8096`, sem exigir `/jellyfin` no cliente. O proprietário
confirmou login e reprodução na TV. Esse encaminhamento é restrito à LAN;
não restaurar publicação WAN ou ligar a edge por causa dele. Os nomes HTTPS
privados continuam pelo Tailscale. Relatos anteriores abaixo são históricos
quando divergem desta atualização ou do estado de implementação.

O Seerr usa `https://overseer.greis.dev.br/`, décimo nome privado, com a
grafia solicitada pelo proprietário e autenticação vinculada ao Jellyfin.
O include é aditivo; preserve o listener LAN e os demais vhosts ao atualizá-lo.

Este repositório é a fonte da arquitetura geral, contratos de integração e
configuração da infraestrutura compartilhada. Aplicações vivem em repositórios
próprios; o catálogo aponta para commits imutáveis e distingue proposta de execução.

Estado observado em 16/11/2026: oito processos nativos do core estão vivos
(quatro Arr, Seerr, integration-proxy, qBittorrent e monitor); API, gateway e
worker estão iniciados em manutenção, sem readmissão da automação. Os 734
torrents continuam parados, um em `missingFiles`. Foram publicados 8.209 caminhos/6.023 arquivos
únicos (5,449 TB), sem os dois aliases degradados. Origens permanecem preservadas
e gatilhos Jellyfin contidos. O proprietário revogou a publicação WAN/VPS/10443:
o desenho atual usa Tailscale para todos os nove serviços, inclusive Jellyfin
em `https://jellyfin.greis.dev.br/jellyfin/`. O A desse nome foi criado para o
controle Tailscale. Os nove hosts responderam HTTP 200 com TLS válido; o novo
nome Jellyfin também passou por DNS normal no Windows/Tailscale, logins comum
e administrador com identidades corretas, catálogo, Range 206 de 64 KiB e
WebSocket 101 com aceite exato. A conta comum foi recusada na rota administrativa
com 403; as duas sessões foram revogadas por logout. O teste usou `ApiKey`
canônico, sem habilitar APIs legadas. O bundle web ainda usa `api_key` no
socket e no download: o Nginx traduz esse token somente nessas duas rotas,
sem substituir credenciais explícitas. A adaptação foi implantada; WebSocket
legado retornou 101 com aceite exato e download legado, 206 de 64 KiB.
Não declarar reprodução interativa completa.
A rota direta
controle → playback:8096 usa autenticação/administração nativas privadas e
mantém mídia RO. Os três containers públicos estão parados; dois DNAT ativos,
quatro hooks persistentes e três exceções dos guests foram removidos.
Convergência do firewall e preservação de controle/playback, SSH, NFS e
masquerade foram conferidas; a conexão WAN foi recusada. Depois, a VM edge
(122) foi desligada de forma limpa, com `onboot=0`; discos e demais
configurações foram preservados. Os nove domínios mantiveram HTTP 200 e TLS
válido pelo Windows/Tailscale após o desligamento. O acesso privado não
depende dessa VM.
Não reabrir a entrada pública por automação ou pelos roteiros históricos.
O wildcard Let's Encrypt privado já cobre os nove nomes. O certificado público
foi retirado de uso, com chaves preservadas fora do Git e métrica desativada.
Os oito domínios administrativos anteriores responderam HTTP 200 com cadeia TLS válida pelo
Windows/Tailscale e DNS normal. Nginx privado escuta somente no IP Tailscale,
na porta 443; portas 22, 8006, 8443, 8080, 3080, 9090 e 9100 foram negadas por
esse caminho. qBit usa somente o proxy administrativo na porta 18080 do core.
Sete checks reais qBit passaram: API anônima 403, login/versão, CSRF inválido
401 mesmo com Referer correto, sessão preservada e logout seguido de 403.
A edge foi impedida de acessar controle:443, core:7878/18080 e PVE:8006/22.
O site legado 8443 foi preservado, com corte explícito
das origens da API/Grafana; somente esses dois containers foram recriados.
DNS continua no Registro.br em modo avançado, sem migração para Cloudflare.
Renovação DNS-01 manual, revisão dos grants, console/upload Proxmox e aceite
reprodução interativa Jellyfin pelo novo nome privado continuam pendentes. DDNS residencial não é
necessário neste desenho. O restart real do Nginx passou com espera
do IP antes de `nginx -t` e HTTP 200 depois; não houve reboot de VM.
O certificado privado mantém alertas no painel: aviso abaixo de 21 dias e
crítico abaixo de 7, ambos por 5 minutos. Eles não renovam TLS automaticamente.
Clientes precisam integrar a tailnet e ter permissão; acesso ao destino 443
compartilhado não concede autorização nas aplicações. Grants não foram alterados.
Não publicar vídeo pelo Tunnel público padrão da Cloudflare sem nova decisão informada:
ver análise em `docs/architecture/access-domains.md`. Consulte o
[estado atual](docs/implementation-status.md); os relatos anteriores abaixo são
históricos e não alteram os limites operacionais.

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
  No bootstrap inicial, a rede privada tinha NAT sem DNAT e filtros testados;
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
  O adiamento inicial do Abyss foi revogado pelo proprietário em 16/11: o tema
  web foi integrado ao consumidor e validado em desktop/celular, sem nova VM.
  Consulte o estado atual e o runbook do mediaserver para revisão e reversão.
  A inspeção da iGPU foi somente leitura, sem passthrough.
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
  estão ativos; 25 painéis foram provisionados (22 com revisão visual anterior). Falha e recuperação de coletor
  e exporter dispararam e resolveram os alertas locais. Reboot do controle
  preservou estado e coleta, invalidando a sessão anterior; seu autostart usa
  ordem 5, antes da mídia. Portal e Grafana passaram no navegador real em
  desktop/mobile, com leitura sem mutações. Shutdown/reboot/start via API foram
  depois comprovados na edge com SO, UPID/boot/SSH; conta temporária revogada.
  Manutenção SQLite horária conserva todas as operações/chaves e evidências não
  resolvidas; poda eventos antigos elegíveis e intenções expiradas em lotes.
  Coletor de playback mede saúde/lease/frescor; alerta obsoleto disparou e resolveu.
  Tampa corrigida via logind e testada fisicamente por 30 s; sem reboot do host.
  Retorno USB foi assistido, não automático. Três fontes foram autorizadas para
  inspeção block-RO e ro,noload, sem replay/reparo; preservar esse escopo.
  Na etapa inicial de restauração, Docker estava instalado no core sem apps
  readmitidos. A ativação parcial posterior e o backend edge estão registrados
  no resumo acima; core e consolidação continuam prioritários.
  A releitura integral SHA-256 do staging foi interrompida pelo proprietário em
  16/11; não retomá-la automaticamente. O critério atual é triagem de reprodução,
  com preservação das origens. Só falha de conteúdo comprovada pode fundamentar
  a exclusão autorizada da cópia; falha de rede/codec/transcode/autorização ou
  caminho ainda não publicado não basta. O piloto de três arquivos não excluiu
  mídia e não comprova a triagem completa.
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
