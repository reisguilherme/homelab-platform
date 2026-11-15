# Estado da implementação

Atualização documental: **15/11/2026**. A publicação inicial de 14/11 estabeleceu
a separação de repositórios na branch `refactor`. **O proprietário instalou
Proxmox no SSD de sistema autorizado, e a entrega do host identificado e
acessível pela rede privada está concluída.** Identidade SSH, sessão com chave
dedicada e HTTPS foram conferidos. O segundo SSD está desmontado com o mesmo
UUID ext4 anterior; os HDs USB permanecem desconectados. Não há VMs ou regras
de firewall configuradas. Restauração, NFS, isolamento e serviços continuam
pendentes; a prontidão de produção permanece falsa. O
[roteiro de instalação assistida](runbooks/proxmox-installation-handoff.md)
preserva a preparação e a passagem realizadas.

| Área | Preparado ou comprovado | Pendente |
|---|---|---|
| Arquitetura | Documentação geral canônica, diagramas e gaps | Aceite físico das hipóteses de isolamento e capacidade |
| Integração | Schemas, template, validador local e catálogo por commit | Conformidade dos manifests e permissões efetivas por projeto |
| Observabilidade | Compose independente com Prometheus/Grafana privados | Ativação, alvos, dashboards, consumo e ensaios no servidor |
| Host Proxmox | Instalação no SSD autorizado, inventário e acesso privado SSH/HTTPS verificados | Configurar e testar isolamento; administrar o host sem depender dos serviços convidados |
| VMs e aplicações | Desenho e ensaio histórico de mídia examinados; backup final do host, projetos e sete volumes selado e conferido no HD | Criar VMs, restaurar estado e validar a retomada; nenhuma VM existe ainda |
| Hub de arquivos | Modelo NFS e autoridade sobre mounts/exports | Consolidação verificada, exports/ACL e clientes reais |
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

**Entrega concluída: host identificado e acessível pela rede privada.** A
checagem não montou discos de mídia, criou VMs, fez deploy ou restaurou serviços.
As próximas etapas são preparar os convidados e a posse exclusiva do storage,
restaurar estado e validar NFS, firewall e isolamento antes da publicação.
K3s permanece futuro. IPs, seriais, UUIDs, fingerprints e chaves ficam somente
na ficha e nas evidências privadas.

## Verificação da separação

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
