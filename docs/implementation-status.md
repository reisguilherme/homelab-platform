# Estado da implementação

Atualização documental: **15/11/2026**. A publicação inicial de 14/11 estabeleceu
a separação de repositórios na branch `refactor`. **O proprietário instalou
Proxmox no SSD de sistema autorizado, e a entrega do host identificado e
acessível pela rede privada está concluída.** Identidade SSH, sessão com chave
dedicada e HTTPS foram conferidos. Depois, core, playback e edge foram criadas
com Ubuntu 24.04, QGA, SSH e NTP operantes. A rede privada com NAT sem DNAT e
filtros dos convidados passou pelos testes TCP e de pacotes registrados abaixo.
O segundo SSD está desmontado com o mesmo UUID ext4 anterior. Autostart
ordenado, acesso e filtros foram conferidos após reboot. Na etapa posterior,
o HD de 18 TB foi entregue exclusivamente ao core, com mount preservado e NFS
RO para playback. Restrição da gestão LAN, restauração, aplicações e recuperação
automática de USB continuam pendentes; a prontidão de produção
permanece falsa. O
[roteiro de instalação assistida](runbooks/proxmox-installation-handoff.md)
preserva a preparação e a passagem realizadas.

| Área | Preparado ou comprovado | Pendente |
|---|---|---|
| Arquitetura | Documentação geral canônica, diagramas e gaps | Aceite físico das hipóteses de isolamento e capacidade |
| Integração | Schemas, template, validador local e catálogo por commit | Conformidade dos manifests e permissões efetivas por projeto |
| Observabilidade | Compose independente com Prometheus/Grafana privados | Ativação, alvos, dashboards, consumo e ensaios no servidor |
| Host Proxmox | Instalação no SSD autorizado, inventário e acesso privado SSH/HTTPS verificados; `vmbr0` preservada | Restringir gestão na LAN; o firewall do host mantém `enable: 0` |
| VMs base | Core, playback e edge `running`, QGA/SSH/NTP operantes, cloud-init concluído; autostart ordenado conferido após reboot | Capacidade sob carga e prontidão das aplicações |
| Rede dos convidados | Bridge privada, NAT sem DNAT, firewall legado ativo; provas TCP/pacotes e persistência dos filtros após reboot conferidas | Revisão da WAN dinâmica, restrição da gestão LAN e aceite dos fluxos de aplicações |
| Aplicações | Ensaio histórico de mídia examinado; backup final selado e conferido no HD | Restaurar estado e validar retomada; sem Docker, apps ou GPU nos guests |
| Hub de arquivos | HD exclusivo do core; NFS RO restrito à playback; negações de escrita e reboot do core conferidos, cliente remontado manualmente | Guards das aplicações, recuperação USB automática e consolidação verificada |
| Energia | Estados e regras de reintegração USB | Nobreak, comunicação, coordenação host/guest e teste de falhas |
| K3s | Critérios de adoção e fronteiras | Recursos adicionais, implantação e contratos dos workloads |

O catálogo inicial registra somente integrações com arquivos publicados e
status `proposed`; não atesta serviço ativo. A integração de métricas de mídia
é a primeira unidade. O contrato do exporter não certifica o restante da stack
de mídia nem transforma Jellyfin em um processo isolado com volume somente leitura.

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

Não houve restauração das aplicações, Docker, GPU, migração ou verificação
global do acervo. Recuperação USB e guards de ausência de mídia nas aplicações
continuam pendentes; `production_ready` e `partial_restart_safe` permanecem
falsos. O backup final único no HD mantém a estratégia e os limites anteriores.

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
