# Estado da implementação

Atualização documental: **16/11/2026**. A publicação inicial de 14/11 estabeleceu
a separação de repositórios na branch `refactor`. **O proprietário instalou
Proxmox no SSD de sistema autorizado, e a entrega do host identificado e
acessível pela rede privada está concluída.** Identidade SSH, sessão com chave
dedicada e HTTPS foram conferidos. Depois, core, playback e edge foram criadas
com Ubuntu 24.04, QGA, SSH e NTP operantes. A rede privada com NAT sem DNAT e
filtros dos convidados passou pelos testes TCP e de pacotes registrados abaixo.
O segundo SSD foi preservado com o mesmo UUID ext4 anterior e agora está
montado somente leitura para inspeção, conforme a atualização abaixo. Autostart
ordenado, acesso e filtros foram conferidos após reboot. Na etapa posterior,
o HD de 18 TB foi entregue exclusivamente ao core, com mount preservado e NFS
RO para playback. Configuração e cache do Jellyfin foram restaurados e
conferidos no core e na playback; Docker e a imagem foram instalados na
playback. Jellyfin iniciou saudável, com API autenticada, catálogo preservado,
leitura HTTP e decodificação por CPU conferidos. O reboot da playback confirmou
retorno automático do NFS RO, Docker e Jellyfin no perfil inicial. Depois,
transcode recebeu SSD dedicado de 32 GiB e as 18 senhas foram redefinidas, com
encode curto por CPU e logins/logouts conferidos. A lease obrigatória foi
implantada; expiração, HOLD e preservação de parada manual passaram. Reboot
com SSD/lease passou e exige readmissão explícita. Restrição da gestão LAN e
recuperação automática de USB continuam pendentes; a prontidão de produção
permanece falsa. O
[roteiro de instalação assistida](runbooks/proxmox-installation-handoff.md)
preserva a preparação e a passagem realizadas.

Na etapa de governança, foi criada **homelab-control**, com 2 vCPU, 2 GiB e
disco virtual de 24 GiB. O core passou de 6 para 4 GiB após medição e parada
limpa; os quatro convidados mantêm 11 GiB no total. A base da VM, a rede e o
nginx com TLS estão operantes. **API, portal, Prometheus e Grafana estão
implantados, com operações reais, coleta, reboot e navegação desktop/mobile
verificados.** Consulte
[Plataforma de controle](#plataforma-de-controle) para o alcance desses ensaios.

| Área | Preparado ou comprovado | Pendente |
|---|---|---|
| Arquitetura | Documentação geral canônica, diagramas e gaps | Aceite físico das hipóteses de isolamento e capacidade |
| Integração | Schemas, template, validador local e catálogo por commit | Conformidade dos manifests e permissões efetivas por projeto |
| Governança | API/portal privados; CRUD/ACL/recursos/TOTP aceitos; shutdown/reboot/start via API em guest com SO comprovados; manutenção SQLite implantada | Controle de serviços dentro dos guests, melhoria visual e reconciliação ambígua |
| Observabilidade | Seis targets ativos; 25 painéis provisionados por API (22 com revisão visual anterior); sinais Jellyfin/lease/frescor e alerta de coletor obsoleto disparado/resolvido | Revisão visual dos três painéis novos, consumo sob carga e sonda independente; canal externo adiado pelo proprietário |
| Host Proxmox | Instalação no SSD autorizado, inventário e acesso privado SSH/HTTPS verificados; `vmbr0` preservada | Restringir gestão na LAN; o firewall do host mantém `enable: 0` |
| VMs base | Três VMs de mídia e homelab-control; QGA/SSH e cloud-init conferidos; core reduzido para 4 GiB, mantendo 11 GiB totais; reboot do controle aceito com autostart em ordem 5 | Capacidade sob carga; reboot isolado do controle não demonstra novo reboot integral do host |
| Rede dos convidados | Bridge privada, NAT sem DNAT, firewall legado ativo; provas TCP/pacotes e persistência dos filtros após reboot conferidas | Revisão da WAN dinâmica, restrição da gestão LAN e aceite dos fluxos de aplicações |
| Aplicações | Jellyfin privado, mídia RO e transcode em SSD de 32 GiB; encode curto por CPU, API, 18 logins/logouts e reboot com readmissão conferidos | Login interativo, cliente externo e capacidade sob carga; automação e GPU ausentes |
| Hub de arquivos | HD exclusivo do core e NFS RO; guard e lease aplicados; expiração, HOLD, parada manual e recusa da lease de boot anterior testados | Recuperação USB automática e consolidação verificada |
| Energia | Estados e regras de reintegração USB | Nobreak, comunicação, coordenação host/guest e teste de falhas |
| K3s | Critérios de adoção e fronteiras | Recursos adicionais, implantação e contratos dos workloads |

O catálogo inicial registra a integração de métricas de mídia como `proposed`;
o exporter ainda não está ativo. `media-playback` está registrada como `deployed`
no commit `fc9a560c613431a0d95b4fb4beb5726792b62750`, com contrato e Compose
próprios no consumidor e aceite privado limitado ao descrito abaixo. O
contrato do exporter não certifica o restante da stack de mídia, e validar um
contrato não comprova implantação nem isolamento em runtime.

## Continuidade operacional de 16/11

A prioridade é [concluir core e consolidação](architecture/operational-priorities-2026-11-16.md).
O [mapa greis.dev.br](architecture/access-domains.md) foi documentado: streaming
público e administração privada. DNS, TLS dos nomes e entrada pública ainda
não foram aplicados. Alertas ficam somente no painel por decisão do proprietário.
Inventário visual de discos, controles por serviço e melhoria do portal seguem
pendentes, sem bloquear a recuperação do acervo.

- **Tampa:** drop-in do logind aplicado sem reboot; quatro observações em 30 s
  com a tampa fisicamente fechada confirmaram SSH e quatro VMs disponíveis, sem
  suspensão. Persistência após reboot do host ainda não foi ensaiada. Ver
  [procedimento](runbooks/notebook-lid.md).
- **USB:** retorno assistido após suspensão/reconexão, com parada normal do
  consumidor, NFS e ext4, shutdown limpo do core e conferência física antes do
  retorno do mesmo passthrough. Backup, catálogo e mídia RO preservados. Não
  houve formatação, force-unmount ou reparo; reintegração automática não foi provada.
- **Storage:** correção de resultados definitivos e reconciliação explícita de
  publicação implantadas. Exige HOLD, nenhum probe pendente, processo terminado,
  lock/journal/identidade/lease expirada e recibo durável. Tempo decorrido não
  libera trabalho. Após readmissão explícita, 135 s atravessaram o cron, com nove
  renovações e sem HOLD indevido.
- **ACPI:** reboot, shutdown e start da edge com SO passaram pela API, com UPID,
  estados, mudança de boot e chave SSH preservada. Uma consulta transitória 503
  não levou à repetição da mutação; a mesma operação reconciliou para sucesso.
  Conta, papel e ACL temporários foram revogados. Não foi ensaio por clique na UI.
- **Auditoria:** manutenção horária, 90 dias, lote de 500, orçamento de lock de
  5 s e SQL de 2 s. Primeira execução removeu uma intenção expirada e nenhum
  evento; as nove operações anteriores ficaram idênticas e `quick_check` passou.
  Todas as operações/chaves e evidências não resolvidas são preservadas, sem
  VACUUM automático. Após os ensaios havia 12 operações e 50 eventos.
- **Playback:** coletor restrito mede HTTP de saúde, lease e frescor sem
  credenciais ou acesso ao acervo. Três painéis/regras novos provisionados e
  consultas/fixtures promtool conferidas. Pausar só o coletor fez
  `PlaybackCollectorStale` atingir firing; restaurá-lo resolveu o alerta, com
  Jellyfin/admissão em 1 e seis targets ativos. HOLD real anterior gerou métrica
  0 e alertas pending; não durou para provar firing desses dois alertas no servidor.
- **Origens:** HDs de 4 TB/1 TB e SSD preservado identificados, block-RO e
  `ro,noload` no Proxmox, dentro da autorização específica. Todos indicam journal
  pendente; sem replay, reparo ou cópia nesta inspeção. O Seagate registra 8
  setores pendentes, 8 offline não corrigíveis, 14 erros reportados e limiar
  histórico de temperatura. Avaliar o que já está preservado antes de novas
  leituras intensivas; SMART geral aprovado não comprova integridade.
- **Core:** Docker/Compose instalados, zero containers. Sete árvores restauradas
  para staging SSD privado novo: 23.566.307.737 bytes, 8.676 arquivos, 718
  diretórios e três links de logs permitidos. Manifesto fixado, hashes dos
  arquivos selecionados e metadados conferidos; não foi repetido o hash integral
  do TAR. Auditoria offline dos seis bancos, incluindo cópia dos sidecars, passou
  em `quick_check`; configuração qBit também foi fingerprintada. Nenhum app do
  core foi readmitido. Tarefas nativas continuam exigindo contenção por versão;
  simples restauração e presença de banco não comprovam inicialização segura.

A medição antes da restauração encontrou 5,65 GiB disponíveis e zero swap no
host, com 11 GiB configurados nas VMs. A [tabela de memória](architecture/operational-priorities-2026-11-16.md)
separa RSS do host e memória disponível nos guests. Arr e workers ainda parados
impedem tratar a amostra como aceite de carga completa.

## Plataforma de controle

API, portal, observabilidade e configuração pública desta etapa foram
publicados na branch `refactor`, no commit
`a8f1c7305afdff5146a6d6e39253e1beac15bf81`.

A VM **homelab-control** foi criada de imagem Ubuntu com hash previamente
verificado: 2 vCPU, 2 GiB de RAM e disco virtual novo de 24 GiB, identificada
pelas tags `homelab`, `governance` e `observability`. QGA, SSH e cloud-init
foram conferidos. O único aviso do cloud-init foi a depreciação de `user` como
string gerado pelo Proxmox. Isso não é erro de inicialização; o aceite das
aplicações é registrado separadamente abaixo.

Antes da criação, o uso físico do pool de aproximadamente 349 GiB era
**19,39%**, com metadata em **1,09%**. Os discos virtuais, incluindo transcode
e controle, somam agora **312 GiB**, além de poucos MiB de cloud-init. A margem
pelo tamanho máximo é de cerca de **37 GiB**; foi escolhida reserva de
**32 GiB**, com perfil de ensaio de 4 GiB. Espaço thin livre não equivale a
reserva garantida: cada operação ainda precisa validar capacidade, metadata
e compromisso lógico atuais.

A redução do core de 6 para 4 GiB ocorreu após medição, desmontagem normal
do NFS na playback e desligamento gracioso. Após o reboot, a chave SSH do
core, o UUID do HD, o NFS e o recibo do backup foram preservados. A playback
retornou saudável; os 807 registros originais de UserData e os seis registros
novos observados permaneceram presentes. Os convidados somam 11 GiB, com o
orçamento de 3 GiB do host e cerca de 1,49 GiB de margem preservado. Nenhum
filesystem do acervo foi formatado nesta etapa.

O nginx TLS está ativo na VM de controle. Seu certificado foi assinado pela
CA existente do Proxmox e a chave privada permaneceu no guest. A origem
privada por túnel local consta da ficha operacional; Grafana usa `/grafana/`.
API, portal, Prometheus e Grafana foram implantados. A API e o coletor estão
saudáveis, a coleta real está ativa e a revisão visual no navegador passou.
Sessões Grafana e Proxmox continuam independentes.

As regras de firewall e antisspoof foram aplicadas. O controle alcançou os
exporters na porta 9100 dos quatro guests; controle → SSH do core/Proxmox
foi negado. Edge e playback → controle nas portas 22, 8080, 8443 e 9100 também
foram negados. A rodada final também confirmou edge/playback → controle
negados por TCP em 22, 3080, 8080, 8443, 9090 e 9100. Esses testes delimitam
os fluxos examinados; a restrição da gestão do host pela LAN continua pendente.

Os exporters de nó estão instalados nos quatro convidados, somente para
leitura. A credencial Proxmox com papel de auditoria também foi criada e
permanece privada. Ela serve à coleta e à prova global de capacidade, por
adapter somente GET; não autoriza mutações humanas. Cada operação usa a sessão
delegada e as ACLs atuais do usuário no Proxmox. A UI passou em dez testes Node
e onze grupos de cenários no Chrome, desktop e mobile, contra API sintética.
Esses checks locais são distintos dos ensaios reais seguintes, de 16/11:

- **14 checks de CRUD, com oito operações concluídas:** criação idempotente,
  CSRF negado, RAM alterada de 384 para 512 MiB, concessão/revogação de ACL,
  usuário de leitura sem poder de mutação nem visibilidade das VMs de mídia,
  start/stop, exclusão, auditoria e logout. A VM descartável tinha 1 vCPU,
  512 MiB e disco de 4 GiB, sem NIC ou SO; foi removida ao final.
- **Cinco checks reais de TOTP:** matrícula efêmera no Proxmox, desafio antes
  de criar cookie, código incorreto negado com desafio consumido, código
  correto com cookie Secure e ACL respeitada, e logout. As identidades de
  ensaio foram revogadas/removidas; os recibos permanecem privados.
- **Seis targets Prometheus ativos:** quatro exporters de guests, coletor
  Proxmox e o próprio Prometheus. O dashboard de infraestrutura tem 22 painéis,
  com provisionamento e visualização real verificados.
- **Falha real de coleta por 150 segundos:** coletor e exporter do controle
  indisponíveis produziram `GuestExporterUnavailable` e
  `ProxmoxCollectionUnavailable` em estado firing. Após restauração, os seis
  targets voltaram e os alertas resolveram. Não havia alerta ativo na
  observação final. Não foi testada entrega por canal externo.
- **Reboot do controle:** mesma chave SSH e novo boot ID, cookie anterior
  rejeitado, 34 eventos e nove operações SQLite preservados, quatro containers
  em execução sem OOM, seis targets ativos e banco Grafana íntegro. O Proxmox
  tem `onboot=1`, ordem 5, espera de partida de 20 s e desligamento de 60 s
  para controle, antes de core 10, playback 20 e edge 30. Esse teste isolado
  não repete o reboot completo do hipervisor nem aceita recuperação física USB.
- **Navegador real:** portal com login de leitura, visão geral, lista/detalhe
  de VMs, recursos/ACL, atividades e logout, em desktop e largura de 390 px,
  sem overflow, exceções ou mutações. Grafana teve login/logout próprios, 22
  painéis e 22 consultas HTTP 200 sem erro; 21 retornaram séries/linhas. A
  consulta de alertas firing não tinha séries e mostrou “Sem dados”, sem
  inventar saúde. Desktop/mobile passaram; capturas ficam privadas.

A conferência final do Jellyfin encontrou container saudável e guard aprovado:
32.373 BaseItems, 432 Permissions, 234 Preferences e 813 UserData (807 originais
e seis adições preservadas), 18 senhas presentes, 20 tarefas ociosas, três
bibliotecas sem realtime e nenhum scan ou erro de aplicação no intervalo
observado. São contagens dessa conferência, não soma de ciclos de teste.

A verificação local final passou em **236 testes pytest** em WSL/Python 3.12,
Ruff check/format de 21 arquivos e dez testes Node da UI. Recibos, corpos HTTP,
cabeçalhos e inventário real permanecem fora do Git.

Login/TOTP usam POST por HTTPS, com formulários desabilitados até a instalação
dos handlers e leitura da sessão. Credenciais não pertencem a URLs; o log do
proxy omite query strings. O [runbook de governança](runbooks/platform-governance.md)
preserva os procedimentos e as limitações dessa entrega.

O portal coordena suas próprias intenções com lock e idempotência. Alterações
paralelas pelo console/API externos não participam desse lock. CPU/RAM usam
digest upstream; energia, exclusão e ACL não oferecem a mesma comparação
atômica. Prévia e revalidação reduzem a janela de concorrência, sem eliminá-la.
Coordenar essas mudanças com o console. Criação inicial entrega hardware
desligado e sem NIC; SO, rede e operações avançadas continuam no Proxmox.

G20/G21 foram atendidos parcialmente pelos ensaios acima e pela continuidade
registrada nesta página. ACPI via API e retenção já foram implantados/ensaiados;
medição sob carga, controles por serviço e revisão visual continuam pendentes. Uma
criação sem resultado rastreável não libera repetição: permanece em
reconciliação e bloqueia novas alocações no nó até prova ou investigação.
Reconciliação sem UPID pode exigir intervenção manual. USB, nobreak, entrada pública,
automação Arr, GPU e HA conservam seus aceites próprios.

## Checkpoints anteriores à instalação

Na preparação inicial, havia apenas checkpoint privado de código/configuração,
sem bancos consistentes, e a verificação da consolidação estava incompleta.
O relato e os checks daquela etapa permanecem no
[registro do projeto de mídia](https://github.com/reisguilherme/homelab-mediaserver/blob/8627cd8ff76411831c95eb0072f88998c27469e0/docs/architecture/homelab-2026/implementation-status.md).

O [checkpoint operacional de 15/11, commit c2973a4](https://github.com/reisguilherme/homelab-mediaserver/blob/c2973a4bbbe51209e1e0895ab2be79fc552b6723/docs/runbooks/operational-checkpoint-execution.md)
verificou cópia Windows, restauração dos arquivos em ext4, 11 bancos SQLite
e importação de 42 imagens. Os 21 serviços originais retornaram com manutenção
preservada; os nove já parados continuaram assim. Isso não comprovou o
funcionamento de aplicações iniciadas a partir da restauração. Os três workers
históricos sem imagem disponível não precisam ser reconstruídos se não forem
necessários à retomada escolhida; seus rootfs permanecem preservados.

Depois desse checkpoint, o [ensaio de inicialização isolada](https://github.com/reisguilherme/homelab-mediaserver/blob/refactor/docs/runbooks/proxmox-preinstallation.md)
examinou 13 serviços em cópias descartáveis: onze tiveram resposta HTTP `200`
e dois componentes de segurança negaram o cliente não confiável com `403`.
As contagens de catálogo monitoradas não mudaram; os SQLite examinados
passaram após a parada. Os daemons de ensaio foram encerrados. Isso comprova
o comportamento observado nos clones, sem comprovar reprodução, GPU,
integração completa ou funcionamento com os discos reais. `production_ready`
e `partial_restart_safe` continuam falsos.

Não é necessário repetir o ensaio do mesmo arquivo intacto. A captura final
ampliada foi selada às 18:08 de São Paulo, em 15/11, com origem estável.
Inclui 36 containers, sete volumes, o outro projeto e configurações do host;
22 containers foram parados de forma limpa e os 14 já inativos foram mantidos.
Foram arquivadas 49 imagens e três rootfs de fallback, ainda sem reconstrução
comprovada. O [roteiro](runbooks/proxmox-installation-handoff.md#captura-final-do-host)
registra contagens e tamanho. Os checksums do conjunto no HD foram conferidos;
o recibo de controle também foi copiado e verificado no Windows.

O proprietário decidiu manter o backup final completo somente no HD de 18 TB
e prosseguir. A transferência final ao Windows foi interrompida; seus arquivos
parciais permanecem incompletos e não são origem válida para restauração.
O checkpoint anterior no Windows continua intacto. A restauração integral do
conjunto final não foi testada, mas segunda cópia e novo ensaio integral não
são pré-requisitos desta instalação por decisão expressa do proprietário.
O HD com mídia passa a ser a única cópia completa do estado final.

A prova global do acervo e um reparo continuam pendentes. Os dois SSDs de 512 GB já
foram identificados no inventário privado: um contém o sistema, outro mídia.
O proprietário autorizou sobrescrever somente o SSD do sistema para Proxmox,
com identidade exata registrada na ficha privada. A instalação foi conferida
nesse dispositivo; a autorização não incluiu o segundo SSD nem os discos USB.
Nenhum identificador privado entra neste repositório.

O inventário ampliado encontrou sete volumes Docker. O checkpoint anterior
cobria somente o volume montado; a captura final incluiu também os seis sem
vínculo atual a containers, incluindo um de cerca de 58 GB. Eles permanecem
preservados no backup final; ausência de uso atual não autoriza descartá-los.

O proprietário confirmou que manterá o adaptador Ethernet USB e reservará o
endereço combinado. A reserva ainda não foi conferida no roteador; os valores
ficam na ficha privada. A instalação requer a ISO x86_64/amd64 para o Intel,
arquivo `proxmox-ve_9.2-1.iso`; ARM64 não é compatível com esse processador.
O [roteiro](runbooks/proxmox-installation-handoff.md#mídia-de-instalação-e-chave-do-operador)
registra o SHA-256 oficial. A ISO local de 1.706.178.560 bytes foi conferida
com esse hash, mantendo tamanho e data de modificação estáveis durante a leitura.
O proprietário concluiu a instalação e o novo host foi conferido por SSH;
gravação do pendrive e cada tela do instalador não foram auditadas separadamente.

Esta atualização é documental: não executa SSH, download de ISO, desligamento,
formatação, montagem ou deploy. Origens e evidências privadas são preservadas.
Os [gaps](architecture/gaps.md) continuam sendo critérios para a migração;
testes locais não substituem reprodução, GPU, rede ou recuperação física.

## Desligamento e preservação dos discos

Em 15/11, às **21:08 UTC (18:08 de São Paulo)**, a captura final foi selada
com o host Ubuntu ainda acessível por SSH. Às **21:24 UTC**, a auditoria confirmou o backup
montado, seu recibo e os 36 containers parados. Às **21:32 UTC**, antes do
desligamento, todos os HDs USB estavam ausentes do inventário de blocos. O
proprietário confirmou que havia desconectado todos eles, esclarecendo a
causa da ausência. O backup e seu recibo haviam sido conferidos antes dessa
retirada; não foi constatada perda do backup.

Às **21:33 UTC**, a checagem confirmou todos os containers parados, `os.sync()`
terminou e `systemctl poweroff` retornou sucesso. Às **21:33:48 UTC**, SSH estava
inacessível. Naquele momento, o desligamento físico ainda não tinha sido
observado; depois, o proprietário concluiu a instalação descrita abaixo.

A decisão de manter o backup final somente no HD continua válida, sem exigir
cópia Windows ou novo ensaio integral. Não reconectar, montar ou reparar
discos automaticamente; preservar o segundo SSD e a identidade dos USBs para
a próxima etapa de storage.

## Host Proxmox entregue

Registro histórico anterior à criação das VMs. A configuração atual está na
[etapa seguinte](#vms-e-rede-privada); zero VMs e firewall sem regras abaixo
descrevem somente este instante inicial.

O fingerprint SSH foi comparado ao console físico, a chave pública dedicada
foi cadastrada e uma segunda sessão `root` com essa chave foi confirmada. O
inventário por SSH de **15/11, 21:56:49 UTC (18:56:49 de São Paulo)** registrou:

| Item observado | Resultado |
|---|---|
| Sistema | `pve-manager 9.2.2`, kernel `7.0.2-6-pve`, instalado no SSD de sistema autorizado |
| Segundo SSD | Mesmo UUID ext4 do inventário anterior, desmontado; os nomes NVMe inverteram entre os sistemas, sem alterar a identidade usada na conferência |
| HDs USB | Ausentes; permanecem desconectados nesta etapa |
| CPU e memória | 6 núcleos, 12 threads e 15,49 GiB de RAM utilizável |
| Capacidade inicial | `local-lvm` vazio, 348,82 GiB livres; cerca de 85 GiB livres na raiz |
| Convidados | Zero VMs; nenhuma aplicação restaurada ou iniciada |
| Serviços do host | Cinco serviços PVE/SSH examinados ativos; nenhuma unit em falha |
| Rede de gestão | Bridge com IP estático, mesmo MAC do adaptador Ethernet USB; gateway e DNS correspondem à ficha privada |
| Firewall | Status `disabled/running`; zero regras configuradas, consulta da API vazia. Serviço em execução não comprova isolamento |

Às **21:57:57 UTC (18:57:57 de São Paulo)**, o HTTPS retornou `200` com
validação pela CA obtida no SSH autenticado, hostname/IP presentes no SAN e
certificado apresentado correspondente ao conferido. O teste não enviou
credenciais ao painel nem alterou a confiança global do Windows. Isso prova
identidade e transporte do painel, não CRUD/ACL de VMs ou isolamento de rede.

**Entrega concluída: host identificado e acessível pela rede privada.** Aquela
checagem não montou discos de mídia, criou VMs, fez deploy ou restaurou serviços.
A etapa posterior criou os convidados descritos a seguir; storage, restauração
e publicação das aplicações ainda dependem dos próprios aceites.
K3s permanece futuro. IPs, seriais, UUIDs, fingerprints e chaves ficam somente
na ficha e nas evidências privadas.

## VMs e rede privada

Esta seção preserva o bootstrap das três VMs de mídia. A criação posterior
da VM de controle e a redistribuição de RAM estão em
[Plataforma de controle](#plataforma-de-controle); não usar a margem inicial
abaixo como espaço disponível atual.

Esta etapa precede a [entrega do storage](#storage-no-core-e-nfs-ro).

O bootstrap autorizado criou três VMs Ubuntu 24.04 amd64 no PVE 9.2.2:

| Papel | vCPU | RAM fixa | Disco virtual |
|---|---:|---:|---:|
| Core | 4 | 6 GiB | 160 GiB |
| Playback | 4 | 4 GiB | 80 GiB |
| Edge | 1 | 1 GiB | 16 GiB |

São 11 GiB de RAM, mais 3 GiB de orçamento do host e margem de 1,49 GiB.
Os discos somam 256 GiB de um pool inicial de 348,82 GiB, deixando 92,82 GiB
planejados (26,61%) pelo tamanho completo dos discos. Isso não é medição de
espaço físico consumido pelo thin pool nem aceite de carga.

A imagem `ubuntu-24.04-server-cloudimg-amd64.img`, release 20261017, teve
assinatura oficial e SHA-256 conferidos. O
[runbook de guests](runbooks/proxmox-guests.md) registra hash, fontes, geração
offline, preflight e aplicação. O gerador não executa deploy; perfil e
inventário reais ficam privados. Nenhum disco físico foi tocado pelo bootstrap.

Todas as VMs estão `running`, com QGA respondendo, SSH por ProxyJump e NTP
sincronizado. As chaves de host foram obtidas pelo QGA antes de confiar no SSH.
Cloud-init terminou com `errors: []` e somente o aviso de depreciação do campo
`user` como string gerado pelo PVE, a revisar antes da versão 27.2.
Após os testes iniciais, `onboot` foi habilitado na ordem **core → playback →
edge**, com ordem inversa de desligamento. Isso ordena as VMs base; não espera
readiness de NFS ou aplicações. Ao fim dessa etapa ainda não havia apps,
Docker, GPU, USB ou NFS de mídia nos convidados.

`vmbr0` permaneceu intacta. A bridge privada fornece NAT de saída sem DNAT.
O backend legado `pve-firewall` está `enabled/running`, com regras por VM;
o host mantém `enable: 0`, deixando a gestão na LAN como gap explícito.
As 21 provas TCP passaram: core → playback:8096 e playback → core:2049 foram
permitidas, e 19 conexões proibidas foram negadas. Os dois casos positivos
usaram **listeners temporários**, sem aplicação: não comprovam Jellyfin,
NFS, export ou mídia somente leitura. A matriz inclui negações entre guests,
para gestão do host/gateway e para o destino Tailscale. DNS e HTTPS Ubuntu
retornaram sucesso nos três guests.

Guards `raw/physdev` verificam origem IP/MAC antes de conntrack e descartam
IPv6. `ebtables` em `INPUT`/`FORWARD` verifica MAC, IP/MAC de remetente ARP e
VLAN. Probes de dois quadros por caso confirmaram incremento dos contadores
DROP para IP/MAC forjados, remetente ARP forjado, VLAN 0/100, 802.1ad 100 e
IPv6, sem zerar contadores. O caso 802.1ad apareceu em `802_1Q` pela representação
do backend legado/kernel. Os hooks são idempotentes e foram preservados pelo
reinício do firewall.

O reboot posterior mudou o boot ID do host e trouxe automaticamente as três
VMs, com QGA respondendo. SSH por ProxyJump manteve as mesmas chaves; HTTPS
do PVE respondeu `200` com CA e identidade IP/SAN validadas. Não houve units
falhadas. As configurações de `vmbr0` e da bridge privada mantiveram seus hashes;
NAT e guards `raw`/`ebtables` persistiram sem duplicatas. O segundo SSD manteve
seu UUID e permaneceu desmontado; os USBs estavam desconectados. Os **21
testes TCP** e DNS/HTTPS Ubuntu nos três convidados passaram novamente após
o reboot. Os probes de quadros descritos acima são da rodada anterior; a
verificação posterior conferiu a persistência das regras e repetiu a matriz TCP.

Os endereços WAN atuais estão bloqueados no egress para evitar hairpin;
revalidá-los quando mudarem e antes da publicação. A publicação continua
fechada até aplicações, autenticação e comportamento na ausência de mídia
serem aceitos; a prova NFS RO posterior está abaixo. Gestão LAN restrita,
carga, GPU, recuperação USB e
nobreak mantêm suas pendências. Não há aceite de isolamento absoluto ou HA;
`production_ready` e `partial_restart_safe` continuam falsos. A escolha de
backup final somente no HD de 18 TB e o alcance das provas anteriores permanecem.

A validação local deste bootstrap em Python 3.12/Linux passou com **94 testes**,
Ruff, formatação, AST e validação de contrato/catálogo. Esses checks locais
complementam as provas do host descritas acima; não iniciaram as aplicações.

## Storage no core e NFS RO

O proprietário autorizou a entrega exclusiva do HD de 18 TB ao core e o
reconectou. Modelo, serial, UUID e capacidade coincidiram no host e no guest;
somente o dispositivo USB foi passado por porta dedicada, preservando a
Ethernet USB no host. SMART passou, sem realocados, pendentes, incorrigíveis
ou CRC nos atributos examinados.

A inspeção usou bloco RO e `ro,noload`. O hash do recibo coincidiu com a
evidência anterior à instalação; 21 hashes de metadados e os tamanhos dos
cinco tar foram conferidos, **sem rehash dos cinco tar nesta etapa**.
Depois de desmontar, o mount RW novo com `errors=remount-ro` completou o
replay do journal, sem erros I/O/ext4 observados. Paths e permissões foram
preservados. Foi acrescentada somente a linha desse UUID ao `fstab` do core,
com `nofail`, timeout de 60 segundos e `pass=0`, sem fsck automático.

NFS 4.1/4.2 sobre TCP 2049 exporta somente `homeserver/media` para playback,
com `ro`, `all_squash` para UID/GID 1000, `subtree_check`, guard `mountpoint`
e `fsid=0`. O cliente NFS 4.2 usa `ro,hard,noauto` em `/srv/media-view/media`.
Um drop-in da unit NFS existente no core exige e acompanha o mount local;
as dependências foram conferidas, sem nova unit no host Proxmox. Portas TCP
dinâmicas internas de `rpc.mountd` permanecem bloqueadas pelo firewall.
Com cliente de teste RW, criar, acrescentar conteúdo, alterar permissões e
remover uma fixture retornaram `EROFS`; leitura por UID 1000 passou. O
namespace não expôs o backup. A fixture própria foi removida, restando somente
`movies` e `tv` visíveis. O
[runbook de storage](runbooks/storage-core-handoff.md) detalha o alcance.

O reboot do core terminou às **23:11:20 UTC de 15/11**, com boot ID diferente,
identidades preservadas, mount local RW automático, NFS 4.1/4.2 ativo e
dependências do drop-in mantidas. Não houve units falhadas ou erros I/O/ext4
observados, e o hash do recibo permaneceu igual. A playback foi desmontada
limpamente antes e remontada manualmente RO depois; `noauto` permanece.
Uma leitura UID 1000 de **64 KiB de um arquivo real** coincidiu por hash com o
core antes/depois, sem leitura integral do arquivo ou teste de reprodução.
Isso não demonstra recuperação automática após falha física do USB.

Ao fim dessa etapa de storage ainda não havia restauração das aplicações,
Docker ou GPU nos convidados. A preparação do Jellyfin descrita abaixo é
posterior. Migração e verificação global do acervo, recuperação USB automática
e prontidão de produção não foram comprovadas. O backup final único no HD
mantém a estratégia e os limites anteriores.

## Jellyfin na playback

A etapa de aplicação usa o Compose independente do
[projeto de mídia](https://github.com/reisguilherme/homelab-mediaserver/blob/fc9a560c613431a0d95b4fb4beb5726792b62750/docs/runbooks/playback-nfs.md).
Docker e a imagem original Jellyfin 12.2, fixada por digest, foram instalados
somente na playback. Configuração e cache foram selecionados do checkpoint
final para o SSD do core e transferidos ao SSD da playback, com hash da
transferência conferido. Em ambas as restaurações, **32.777 arquivos regulares,
25.497 diretórios e 12.944.183.365 bytes** tiveram conteúdo e metadados
verificados. A referência restaurada permanece separada da cópia de trabalho.
Nenhuma mídia foi migrada, formatada ou removida por essa operação.

O container iniciou saudável, com HTTP privado na porta 8096, e recebe mídia
por NFS RO confirmado, com configuração e cache graváveis no disco virtual
local. A preparação offline preserva bancos e desabilita agendas
nativas e monitoramento em tempo real enquanto o acervo está parcial; plugins
ficam separados da configuração ativa. O perfil inicial usou CPU e tmpfs de
512 MiB; depois foi substituído pelo SSD dedicado descrito abaixo. Nenhuma GPU
foi entregue à VM. Esses aceites não comprovam dez reproduções, transcode 4K
ou operação contínua sob carga.

O drop-in da unit Docker existente na playback exige o mount NFS, inclusive
com `noauto` mantido no `fstab`. O guard do consumidor verifica identidade,
origem e modo somente leitura do mount antes de iniciar e acompanha mudanças
durante a execução. As fixtures de mount ausente/estranho e encerramento do
processo passaram. O reboot da playback mudou o boot ID e trouxe o NFS RO
automaticamente pela dependência do Docker, mantendo `noauto` no `fstab`.
Docker voltou ativo e Jellyfin saudável, com contador de reinícios do container
em zero. Nenhuma unit foi criada no host Proxmox.

Na referência anterior à redefinição de senhas, a API autenticada confirmou
20 tarefas ociosas sem gatilhos e três bibliotecas
sem monitoramento em tempo real. A identidade original do servidor e os 18
usuários foram preservados, sem erros nem execução de scans nos logs
examinados. SQLite passou na verificação de integridade; os hashes comparados
coincidiram com a referência em 32.373 itens de catálogo, 18 usuários, 807
registros de histórico, 432 permissões e 234 preferências. No catálogo, a
comparação cobriu identificação, tipo, nome, hierarquia e caminho dos itens,
sem declarar hash de toda a base.

Uma requisição de mídia autenticada retornou HTTP `206`; os 64 KiB recebidos
coincidiram por hash com a leitura NFS. A decodificação por CPU processou três
segundos e 72 frames, sem alteração do histórico. Autenticação usou uma chave
API existente: login interativo por senha, reprodução em cliente externo e
capacidade sob carga não foram testados.

Após o reboot, autenticação, identidade, hashes do catálogo/usuários/histórico
e contenção de scans passaram novamente. As 20 tarefas continuaram ociosas
sem gatilhos, e as três bibliotecas mantiveram monitoramento em tempo real
desabilitado; não houve erros nem execução de scans nos logs examinados. O
core recebeu resposta de saúde `Healthy` na porta 8096. A edge continuou sem
acesso às portas 8096 e 18096 da playback. Isso não comprova falha/retorno
físico do HD USB ou reprodução pela internet.

Arr, qBittorrent, controlador e workers permanecem parados; o Compose monolítico
não foi iniciado. A edge e a publicação WAN continuam fechadas.

### Transcode SSD e acesso às contas

O proprietário autorizou o novo disco virtual de **32 GiB em `local-lvm`**,
conectado como `scsi1` da playback. Recebeu ext4 e mount por UUID em
`/srv/transcode`; o container usa a subpasta de dados RW e um marcador de
identidade RO. A mídia permanece RO e o limite de RAM do container é **3 GiB**,
sem alteração. Nenhum disco físico ou acervo foi formatado nessa entrega.
Guard correto, mount ausente, UUID divergente, escrita como UID 1000 e marcador
RO passaram nas provas reais. Um reboot posterior confirmou retorno do SSD
por UUID, NFS RO e Docker, com readmissão explícita antes do Jellyfin saudável.

O encode CPU `libx264` produziu **10,01 s em 720p**, em **1,149 s**, com
**281.888 bytes**. Somente a saída de teste própria foi removida e `UserData`
permaneceu igual; o trecho não prova carga contínua ou reprodução em cliente.

As **18 senhas distintas de dez caracteres aleatórios** foram redefinidas
pela API e passaram em login/logout. Políticas permaneceram iguais, salvo três
`InvalidLoginAttemptCount` zerados naturalmente pelo login correto. Hashes
de 807 `UserData`, 432 `Permissions` e 234 `Preferences` permaneceram estáveis.
A relação em texto simples fica somente no Windows privado, sem nomes, valores
ou caminhos privados publicados. Abyss foi adiado e não foi instalado.

Na inspeção seguinte, `UserData` tinha **813 registros**. A comparação confirmou
os 807 originais idênticos e seis adições observadas enquanto a aplicação estava
disponível. Esses registros foram preservados, sem rollback; o hash do conjunto
atual não é o hash original de 807 registros. O teste de encode acima mantém
seu recibo próprio sem alteração de `UserData`; as adições não são atribuídas
a esse teste. A conferência posterior ao reboot preservou os 807 originais e
as seis adições; BaseItems, Permissions e Preferences também coincidiram.

A inspeção da iGPU Intel encontrou grupo IOMMU isolado, somente em leitura;
não houve passthrough ou teste de aceleração.

### Admissão obrigatória de storage

As VMs do consumidor foram identificadas como `mediaserver-core`,
`mediaserver-playback` e `mediaserver-edge`, com tag `mediaserver` e papel
correspondente. A tag `homelab` fica reservada à plataforma. IDs, discos e rede
foram preservados. Como o metadata automático do cloud-init deriva também
do nome, as identidades atuais foram fixadas em snippets próprios. O segundo
reboot da playback preservou sua chave SSH; os próximos boots dos outros
convidados ainda precisam dessa conferência. Renomeação não é prova de
governança; a implantação e os ensaios posteriores de API/portal/dashboards
estão registrados em [Plataforma de controle](#plataforma-de-controle).

A lease implantada dura até **45 segundos**, vinculada
ao boot do guest, e o consumidor a recusa se estiver ausente, inválida ou
expirada. Falhas mantêm `HOLD`; `resume` explícito exige prova nova do storage.
O coordenador não executa start, mas readmissão pode permitir retorno pela
política Docker `unless-stopped`; parada manual via Docker permanece respeitada.
O consumidor foi aceito saudável com lease obrigatória. A expiração sintética
enviou TERM ao filho em 11,502 s; HOLD real deixou HTTP indisponível e nenhum
processo Jellyfin ativo. Uma parada manual pelo Docker permaneceu após READY;
somente start explícito retomou o serviço saudável. O cron usa watch de 58 s,
deadline de probe de 15 s e TTL máximo de 45 s. A cadência inicial mais curta
causou HOLD indevido na passagem ao cron e foi corrigida; comando ocupado
retorna 75, sem afirmar que a readmissão ocorreu.

A observação contínua por 135 segundos atravessou duas passagens de minuto
com o coordenador armado e autorizações saudáveis, sem HOLD indevido.

**Não há retorno integral desassistido:** lease de outro boot deve ser
recusada, com prova nova e readmissão explícita. O ensaio de reboot com SSD/lease
passou, incluindo a recusa anterior à readmissão; reboot do Proxmox exige auditoria do estado do coordenador
antes da readmissão. O
[runbook de storage](runbooks/storage-core-handoff.md) separa esse contrato da
recuperação física ainda não comprovada.

O guard de mount não detecta necessariamente HD desligado com NFS `hard`
ainda registrado; operações podem bloquear no kernel. Falha/retorno físico
do USB, reintegração coordenada, GPU, consolidação do acervo, restrição da
gestão LAN e nobreak continuam pendentes. `production_ready` e
`partial_restart_safe` permanecem falsos.

## Verificação histórica da separação

- Python 3.12/WSL2, ambiente independente e `uv.lock`: `make lint` e
  `make validate` passaram. Template, catálogo e contrato `media-metrics` foram
  validados pela CLI local.
- Plataforma: 60 testes passaram e 8 foram pulados pela ausência de Docker
  Compose no WSL. A suíte de observabilidade também foi executada no Windows:
  14 passaram, incluindo normalização de Compose e override de dashboard.
  Há sobreposição entre essas rodadas; não somar como testes distintos.
- Consumidor de mídia: 113 testes pertinentes passaram e 1 check de Compose
  foi pulado no WSL. O Compose do consumidor foi conferido separadamente com
  ambiente fictício e CLI Windows, sem daemon.
- Revisão independente conferiu fronteiras, schema, links, ausência de
  credenciais administrativas e distinção entre preparação e runtime. Os
  ajustes de links e exclusão de overrides privados foram incorporados.

Esses checks não iniciaram containers nem exerceram Proxmox, disco USB, NFS,
firewall ou reprodução. A sequência de publicação fixa o schema no consumidor
e só depois registra o commit consumidor no catálogo.
