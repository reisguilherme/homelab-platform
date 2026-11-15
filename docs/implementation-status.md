# Estado da implementação

Atualização documental: **15/11/2026**. A publicação inicial de 14/11 estabeleceu
a separação de repositórios na branch `refactor`. O proprietário autorizou
indisponibilidade. O checkpoint anterior de mídia teve retorno dos serviços;
na captura final, os 22 containers ativos foram parados e permanecem assim.
O host Ubuntu continua ligado, com SSH disponível; Proxmox não foi
instalado. O [roteiro de instalação assistida](runbooks/proxmox-installation-handoff.md)
está preparado, sem autorizar sobrescrita de SSD ou declarar a preparação concluída.

| Área | Preparado neste repositório | Pendente |
|---|---|---|
| Arquitetura | Documentação geral canônica, diagramas e gaps | Aceite físico das hipóteses de isolamento e capacidade |
| Integração | Schemas, template, validador local e catálogo por commit | Conformidade dos manifests e permissões efetivas por projeto |
| Observabilidade | Compose independente com Prometheus/Grafana privados | Ativação, alvos, dashboards, consumo e ensaios no servidor |
| Proxmox/VMs | Desenho, fronteiras, roteiro e inicialização isolada da mídia examinada; captura final do host, projetos e sete volumes selada | Segunda cópia completa e restauração final verificadas, SSD e escopo autorizados e instalação |
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
registra contagens e tamanho. A transferência completa ao Windows começou,
mas sua conferência e a restauração desse novo conjunto ainda estão pendentes;
somente o recibo de controle já foi copiado e verificado no Windows.

A prova global do acervo e um reparo continuam pendentes. Os dois SSDs de 512 GB já
foram identificados no inventário privado: um contém o sistema, outro mídia.
O SSD do sistema é o candidato, ainda sem autorização de sobrescrita; a
autorização será solicitada com a preservação fechada e o escopo concreto.
Nenhum identificador privado entra neste repositório.

O inventário ampliado encontrou sete volumes Docker. O checkpoint anterior
cobria somente o volume montado; a captura final incluiu também os seis sem
vínculo atual a containers, incluindo um de cerca de 58 GB. Sua segunda cópia e restauração
ainda precisam ser conferidas; não se presume que volumes órfãos sejam descartáveis.

O proprietário confirmou que manterá o adaptador Ethernet USB e reservará o
endereço combinado. A reserva ainda não foi conferida no roteador; os valores
ficam na ficha privada. A instalação requer a ISO x86_64/amd64 para o Intel,
arquivo `proxmox-ve_9.2-1.iso`; ARM64 não é compatível com esse processador.
O [roteiro](runbooks/proxmox-installation-handoff.md#mídia-de-instalação-e-chave-do-operador)
registra o SHA-256 oficial. A ISO local de 1.706.178.560 bytes foi conferida
com esse hash, mantendo tamanho e data de modificação estáveis durante a leitura.
Gravação do pendrive e teste de boot ainda não foram verificados; nenhuma
sobrescrita de SSD está liberada.

Esta atualização é documental: não executa SSH, download de ISO, desligamento,
formatação, montagem ou deploy. Origens e evidências privadas são preservadas.
Os [gaps](architecture/gaps.md) continuam sendo critérios para a migração;
testes locais não substituem reprodução, GPU, rede ou recuperação física.

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
