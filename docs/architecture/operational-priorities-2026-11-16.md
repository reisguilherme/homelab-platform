# Prioridades operacionais em 16/11/2026

**Atualização posterior:** a operadora recusou portas/IP fixo para PF, segundo
o proprietário. VPS foi recusada e depois foi aceito Jellyfin público em
`:10443` com DNS-01/DDNS e serviços privados por Tailscale usando o domínio,
conforme [domínios e acesso](access-domains.md). A proposta privada reutiliza
o controle como proxy HTTPS na porta 443, com registros DNS para seu IP Tailscale, sem
resolvedor adicional. Cloudflare é opcional; provedor e automação DNS ainda
não foram escolhidos e não houve migração de nameservers. A orientação
anterior de aguardar liberação de 80/443 é histórica. TLS público, Tailscale
e domínios privados ainda não foram implantados e aceitos.

**Avanço no mesmo dia:** 8.209 caminhos/6.023 arquivos únicos (5,449 TB) foram
publicados no HD de 18 TB; os dois aliases degradados ficam excluídos e as
origens preservadas. Oito processos nativos do core estão vivos; API, gateway
e worker estão em manutenção, sem readmissão das automações. Os 734 torrents
permanecem parados, um em `missingFiles`.
Backend edge, isolamento e 33 checks do proxy foram aceitos. DNAT TCP 80/443
foi aplicado; a publicação segue em ativação, sem certificado TLS após timeouts
externos do ACME e do 4G em 80/443. A regra temporária WAN 10443 → LAN 443 está
ativa e a chegada externa foi capturada, ainda sem TLS. Naquele momento, a
preferência era resolver primeiro 80/443 para URL sem porta; essa decisão foi
substituída pelo aceite de 10443 acima. A captura não comprova certificado ou
reprodução externa, que continuam pendentes.
Os gatilhos Jellyfin seguem contidos. O [estado atual](../implementation-status.md)
detalha as provas; a sequência abaixo registra a prioridade e o planejamento
anteriores, não afirma que todas as etapas ainda estejam por começar.

O proprietário definiu como prioridade **concluir o mediaserver-core e reunir
toda a mídia no HD de 18 TB**. Melhorias visuais do painel, inventário físico,
controle de serviços dentro das VMs, memória e domínios continuam no escopo de
evolução, depois dessa entrega. Este registro orienta a ordem do trabalho; não
declara consolidação concluída nem implanta alterações.

## Core e consolidação primeiro

O requisito é preservar toda a mídia e manter as origens intactas, somente
leitura durante a consolidação. A existência de mídia no destino não demonstra
que todo o acervo foi transferido e verificado. O journal de consolidação tem
pendências e precisa ser confrontado com os arquivos reais antes de retomar
cópias ou declarar conclusão. Aqui, journal é o registro da migração de mídia,
separado da auditoria SQLite da plataforma de controle.

Sequência de trabalho a conferir com o estado real:

1. Confirmar identidade, disponibilidade e saúde do storage do core e das
   origens reconectadas. Preservar `HOLD`, leases e pausas manuais até haver
   prova atual suficiente para cada consumidor. Mount presente não comprova
   saúde física.
2. Reconciliar o inventário das origens e do destino com o journal: itens
   concluídos, pendentes, interrompidos, ausentes e conflitantes. Conferir os
   caminhos e identidades adaptados ao Proxmox; não reutilizar cegamente alvos
   ou premissas do monólito.
3. Consolidar somente o escopo de mídia autorizado no HD de 18 TB, com origens
   RO e sem apagar ou sobrescrever conflitos silenciosamente. A captura final
   e os checkpoints preservados não são pastas de mídia a reorganizar. Não
   formatar, reparar filesystem, alterar partições ou ampliar o escopo de
   mounts como efeito colateral da cópia.
4. Verificar a cobertura do acervo e a consistência entre arquivos, tamanhos,
   verificações de conteúdo e journal. Registrar o método e seu alcance;
   divergências precisam de resolução explícita. Um recibo de captura com
   hash preservado não é um hash global de toda a mídia.
5. Concluir a restauração/configuração dos componentes atribuídos ao core nos
   manifests do consumidor, respeitando as fronteiras com playback e edge.
   Não iniciar o Compose monolítico nas novas VMs. Readiness, integração com
   dados reais e orçamento de recursos precisam de evidência própria.
6. Conferir playback com mídia NFS RO e a política de retomada. Manter gatilhos
   de scan suspensos enquanto o acervo estiver parcial; `resume` requer ação
   explícita e prova nova, preservando paradas manuais.

Inventários detalhados, caminhos privados, bancos, journals e recibos ficam
fora do Git. A decisão existente de manter a única captura final completa no
HD de 18 TB continua válida; este registro não introduz uma segunda cópia
obrigatória ou um gerenciador de backups.

O aceite precisa apontar quais origens e categorias de mídia foram cobertas,
como cada pendência do journal foi resolvida e quais verificações passaram.
Contagem de arquivos, diretórios presentes ou aplicação saudável isoladamente
não encerram a consolidação. O core só estará concluído quando os componentes
previstos para essa etapa e suas integrações estiverem verificados, com limites
e pendências restantes registrados no
[estado de implementação](../implementation-status.md).

## Melhorias registradas para depois

| Necessidade do proprietário | Situação e próximo trabalho |
|---|---|
| Melhorar o visual do painel | A insatisfação com a apresentação está registrada. Redesenho visual fica posterior à entrega de core e mídia. |
| Enxergar os discos físicos | A ausência no painel de governança indica uma lacuna de inventário/apresentação; não prova ausência, desconexão ou perda do disco. Correlacionar inventário físico, passthrough, discos virtuais, pools Proxmox e filesystems dos guests. |
| Ver e controlar serviços por VM | O portal gerencia ciclo de vida e recursos de VMs; status e start/stop/restart de cada aplicação dentro do guest ainda não são uma capacidade suportada. Definir integração por consumidor, permissões e auditoria antes de adicionar controles. |
| Rever o aumento de RAM observado | Medir consumo real e pressão com os workloads previstos antes de reduzir alocações ou aumentar capacidade. Distinguir recursos configurados dos efetivamente consumidos. |
| Usar os domínios próprios | Registrar o [mapa público/privado solicitado](access-domains.md), mantendo DNS, TLS, WAN e Tailscale como implantação pendente. A escolha da automação DNS não bloqueia o core. |

O inventário físico necessário à cópia pertence à prioridade atual. A melhoria
de sua apresentação no painel pode vir depois. Não concluir que o HD de 18 TB
está ausente porque uma tela mostra apenas os discos virtuais ou pools do
Proxmox; também não usar sua presença visual como prova de integridade.

Para memória, comparar RAM alocada às VMs, uso residente observado pelo host,
memória disponível dentro dos guests, cache recuperável, ballooning quando
aplicável, swap, OOM e pressão sob carga. Medir picos de reprodução/transcode,
coleta e aplicações do core quando estas forem readmitidas. Uma porcentagem
isolada não informa quanto pode ser retirado sem degradar os serviços. Este
registro não altera limites nem fixa um novo tamanho de RAM.

Na medição somente leitura realizada pela coordenação em 16/11/2026, o host
tinha **15,49 GiB totais**, **5,65 GiB de `MemAvailable`** e **zero uso de swap**.
As VMs somavam **11 GiB configurados**:

| VM | RAM configurada | Uso no guest: `MemTotal - MemAvailable` | RSS do processo QEMU no host |
|---|---:|---:|---:|
| homelab-control | 2 GiB | 757 MiB | 2,03 GiB |
| mediaserver-core | 4 GiB | 440 MiB | 1,82 GiB |
| mediaserver-playback | 4 GiB | 701 MiB | 2,92 GiB |
| mediaserver-edge | 1 GiB | 280 MiB | 0,51 GiB |

São medidas de perspectivas distintas: o RSS inclui páginas residentes do
processo da VM, enquanto o cálculo no guest considera sua memória disponível.
Não somar essas colunas como consumos independentes nem contar cache duas vezes.
Os workers nativos Arr ainda estavam parados; esta amostra não é uma referência
final sob carga. Falta uma medição comparável da stack anterior para quantificar
o aumento percebido pelo proprietário. Manter o core em 4 GiB durante a
restauração e reavaliar com as aplicações em uso, sem redução automática agora.

O controle futuro de serviços deve preservar a responsabilidade de cada
consumidor e as pausas manuais. Um link para a aplicação ou uma VM ligada não
equivale a serviço saudável, e a gestão de VMs não concede automaticamente
acesso ao daemon Docker dos guests. Ver a
[arquitetura de operações](operations.md).

## Limites deste registro

Nenhum redesenho, controle por serviço, ajuste de RAM, alteração de DNS, abertura
de porta ou publicação foi executado por esta documentação. Recuperação USB
assistida, teste da tampa e lease de contenção não demonstram recuperação
integral desassistida; os limites permanecem no
[runbook de storage](../runbooks/storage-core-handoff.md) e na
[arquitetura de energia](power-recovery.md). Os próximos registros de execução
devem separar o que foi solicitado, o que foi aplicado e o que foi medido.
