# Arquitetura geral do homelab

Fonte canônica da arquitetura geral a partir de 14/11/2026. A separação entre
plataforma e projetos foi aprovada; publicar estes arquivos não instala Proxmox,
VMs, K3s, storage remoto ou serviços. O proprietário autorizou indisponibilidade
em 15/11/2026; a inicialização da mídia já foi examinada em clones isolados,
com limites descritos no [estado da implementação](../implementation-status.md).
A captura final do host, projetos e sete volumes foi selada; os 22 containers
antes ativos continuam parados, e o host permanece acessível por SSH. A
instalação depende da segunda cópia e restauração final verificadas, além do
SSD/escopo autorizados. A posse dos repositórios não implanta a nova topologia.

A proposta inicial continua sendo **um nó Proxmox e três VMs: entrada, reprodução
e núcleo privado**, com Compose nos convidados. O núcleo mantém storage e automação
de mídia próximos para preservar as garantias atuais; Jellyfin recebe mídia RO.
NAS dedicado e K3s são evoluções condicionadas a recursos, contratos e ensaios.

| Documento | Conteúdo |
|---|---|
| [As-is](as-is.md) | Aplicação de referência, observação anterior e limites de evidência |
| [To-be](to-be.md) | Alternativas, VMs, rede, storage, recursos e evolução para três nós |
| [Operação](operations.md) | Controle completo privado, observabilidade, auditoria e orçamento |
| [Energia e recuperação](power-recovery.md) | Nobreak pendente, mecanismo local e coordenação host/core/NFS proposta |
| [Segurança](security.md) | Ameaças, evidência estática, confiança e testes de isolamento |
| [Gaps](gaps.md) | G01–G24, decisões, critérios de aceite, migração e retorno |
| [Repositórios](../repositories.md) | Fonte de cada artefato e contrato obrigatório dos consumidores |
| [Contrato de integração](../integration-contract.md) | Schema e validação local; limites de autorização e readiness |
| [Observabilidade preparada](../observability.md) | Configuração central opt-in e integração com exporters |
| [Instalação assistida](../runbooks/proxmox-installation-handoff.md) | Passagem física, proteção dos discos e reconexão ao host; pendências antes de apagar Ubuntu |

Os diagramas ficam em Mermaid junto ao texto. Não há cópia do HTML antigo nem
dependência de um render local para ler esta arquitetura.

## Decisões e premissas preservadas

| Item | Estado |
|---|---|
| Compute informado | i7-10750H, 16 GB DDR4; dois SSDs de 512 GB identificados no inventário privado, ocupados por sistema e mídia; saúde e margem exigem validação |
| Mídia informada | HD USB de 18 TB; a observação anterior ainda encontrou quatro volumes na união |
| Demanda | Até dez reproduções, upload anunciado de 300 Mbit/s; desempenho não medido |
| Internet | IP público relatado; CGNAT, IPv6 e acesso externo não comprovados |
| Público | Jellyfin com login individual; administração privada |
| Escrita Jellyfin | As-is permite edições/legendas; **to-be confirmado** é mídia RO e alterações privadas |
| Administração | Controle completo de VMs confirmado; Proxmox + Grafana + operações da aplicação propostos |
| Energia | Notebook na bateria e fonte do USB sem AC relatados; ensaio físico pendente |
| Recuperação | Reintegração automática exigida após validações; identidade, integridade ou readiness incertas bloqueiam retomada |
| Nobreak | Aquisição pendente; modelo, carga, autonomia e comunicação ainda não definidos |
| Orquestração | Compose em VMs inicialmente; K3s futuro seletivo |
| Seerr | Privado inicialmente é recomendação; futura publicação exige revisar a superfície pública |
| Continuidade | Instâncias únicas; sem promessa de HA ou RPO/RTO ainda definidos |

18 TB nominais são aproximadamente 16,37 TiB antes de overhead, por conversão de
unidade. Dois SSDs não significam pool de 1 TB livre, espelho ou capacidade
reservada. Upload, USB, codecs, transcodes, temperatura e clientes exigem medição.

## Fronteiras da evolução

O processo público deve sair do kernel de convidado e dos segredos da automação;
o hypervisor permanece dependência comum. A plataforma possui rede, recursos,
dispositivo físico e exports; o consumidor preserva capacidade, permits/claims,
hardlinks, importações e exclusões coordenadas. Uma autoridade por incidente
coordena a recuperação de storage, sem duplicar recuperadores independentes.

Arquivos NFS, discos virtuais Proxmox e objetos S3 têm contratos diferentes.
Mergerfs não é RAID, réplica ou storage distribuído. Mais computes não tornam
USB, hub, energia ou GPU redundantes. O firewall fora da VM pública é obrigatório;
conter comprometimento do próprio hypervisor exige barreira de rede independente.

A área privada reúne visibilidade e controle, preservando acesso direto ao
Proxmox quando core/Grafana falham. Telemetria não recebe administração global.
O [contrato de cada consumidor](../repositories.md) declara recursos, rede,
storage, saúde, segredos por nome e recuperação; validá-lo não concede permissões.

## Evidência e limites

Os guias foram migrados da arquitetura de mídia preservada no
[commit de referência](https://github.com/reisguilherme/homelab-mediaserver/tree/8627cd8ff76411831c95eb0072f88998c27469e0/docs/architecture/homelab-2026).
Links de código usam esse commit imutável; as fontes primárias de produto foram
preservadas com o contexto da revisão original de 14/11/2026. Não constituem
verificação contínua de versões ou novas recomendações de compra.

A análise original era estática e usava um working tree extenso; uma preparação
posterior registrou SSH, checks locais e checkpoint privado. O [as-is](as-is.md)
distingue essas evidências. O checkpoint inicial de configuração não incluía
bancos. O checkpoint operacional posterior, referenciado no as-is, conferiu
cópia Windows, arquivos restaurados e 11 SQLite. Naquela etapa não iniciou
aplicações da restauração; o ensaio posterior examinou 13 serviços em clones,
conforme o as-is. O conjunto final posterior já foi capturado, mas sua cópia
completa Windows e restauração ainda não foram aceitas. A presente separação não
repete SSH, inventário, scan de imagens, pentest ou ensaios físicos. Testes locais
não comprovam Tailscale, firewall, USB, GPU, WAN ou reprodução em clientes.

Não versionar `.env`, bancos, tokens, mídia, inventário bruto ou evidências
privadas. Não formatar/particionar, alterar mounts/fstab ou instalar hypervisor
sem dispositivos, escopo e autorização próprios. Não ativar RTX, reescrever o
serviço Lenovo, abrir portas no roteador ou publicar administração qBit na internet.
Preservar acervo, origens e pausas manuais; não apagar mídia automaticamente.
Não criar CI/CD, releases próprias, gerenciador de backups ou units do host.
Cópias verificadas e restauração são requisitos operacionais, sem introduzir essas
camadas no projeto.
