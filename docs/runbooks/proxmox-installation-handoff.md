# Passagem para instalação assistida do Proxmox

Preparado em **15/11/2026**. O proprietário autorizou indisponibilidade, o
desligamento limpo e a sobrescrita **somente do SSD de sistema identificado
na ficha privada para instalar Proxmox**. O segundo SSD e todos os discos USB
devem ser preservados. **A instalação foi concluída pelo proprietário no SSD
autorizado, e a entrega do host identificado e acessível por SSH/HTTPS foi
verificada.** A etapa posterior criou três VMs Ubuntu e a rede privada filtrada,
com autostart após reboot conferido. Depois, o HD de 18 TB foi entregue
exclusivamente ao core, com NFS RO para playback testado. Restauração,
aplicações, recuperação USB automática e restrição da gestão na LAN continuam
pendentes, conforme o
[estado atual](../implementation-status.md#storage-no-core-e-nfs-ro). O
[registro canônico](../implementation-status.md#host-proxmox-entregue) contém
o inventário sanitizado e o alcance das verificações.
O proprietário decidiu manter o backup final completo somente no HD de 18 TB
e prosseguir sem concluir a cópia Windows ou fazer nova restauração integral.
Essa decisão substitui os pré-requisitos anteriores de segunda cópia e ensaio
final; não amplia a autorização de sobrescrita a outros dispositivos. Este
roteiro não instala, reinicia, formata ou monta dispositivos.

## O que já foi comprovado

O [checkpoint de mídia no commit c2973a4](https://github.com/reisguilherme/homelab-mediaserver/blob/c2973a4bbbe51209e1e0895ab2be79fc552b6723/docs/runbooks/operational-checkpoint-execution.md)
preservou o estado sob quiescência, conferiu a cópia Windows e restaurou os
arquivos em ext4 no WSL. Foram comparadas 259.318 entradas do manifesto, além
de 16 pais implícitos, e os 11 bancos SQLite passaram em `integrity_check`.
As 42 imagens disponíveis foram importadas em daemon isolado. Os mesmos 21
serviços originais voltaram; os nove já parados permaneceram assim. Manutenção,
montagens e outro projeto foram preservados; cron e recuperação USB retornaram.

Esse resultado não exige refazer o ensaio do mesmo arquivo intacto. Naquela
etapa nenhuma aplicação foi iniciada a partir da restauração. Os três rootfs de workers
históricos inativos foram preservados, mas não têm reconstrução comprovada;
não é necessário reativá-los para instalar a plataforma se não fizerem parte
da retomada escolhida. A persistência legada Mosquitto tem bytes e metadados
conferidos, sem prova semântica. Sua necessidade deve ser classificada antes
de incluí-la no escopo funcional.

O [ensaio posterior de inicialização isolada](https://github.com/reisguilherme/homelab-mediaserver/blob/refactor/docs/runbooks/proxmox-preinstallation.md)
examinou **13 serviços** em cópias descartáveis: onze tiveram HTTP `200` e os
dois componentes de segurança negaram o cliente não confiável com `403`.
Não houve mudança nas contagens de catálogo monitoradas; os SQLite examinados
passaram após a parada. Os daemons de teste foram encerrados. Cinco guardas
recusaram o ambiente sem discos; o desvio para observar as aplicações ficou
restrito aos clones. APIs protegidas de Jellyfin/Bazarr responderam `401`,
readiness de controle/telemetria ficou `503` e o health de Byparr retornou `502`
sem rede externa. Reprodução, GPU, automação e integração completa não foram
aceitas; o documento do consumidor detalha o alcance por serviço.

### Captura final do host

A captura ampliada foi **selada em 15/11, às 18:08 de São Paulo (21:08 UTC)**,
com estabilidade dos metadados de origem e checksums no HD confirmados. Incluiu o estado posterior
ao checkpoint anterior, o outro projeto, configurações do host e os **sete
volumes Docker**. Seis desses volumes não tinham vínculo atual a containers;
um deles contém cerca de 58 GB. Todos foram preservados.

O conjunto cobre 36 containers: os **22 que estavam ativos foram parados
de forma limpa**, e os 14 já inativos foram preservados. Na selagem, o host
continuava ligado e acessível por SSH. O retorno dos 21 serviços descrito
acima pertence ao checkpoint anterior, não ao estado posterior à captura.

O manifesto registra 313.827 entradas, 189.935 arquivos regulares únicos e
129.461.539.241 bytes lógicos. Foram arquivadas 49 imagens e três rootfs de
fallback, cuja reconstrução não está comprovada. Os cinco arquivos tar somam
124.487.675.904 bytes; o conjunto listado no recibo soma 124.604.820.080 bytes,
sem contar o próprio recibo. Esses números descrevem a captura selada, não
uma restauração já aceita. O acervo, o reparo e a publicação incremental
continuam no escopo do consumidor.

Depois da selagem, o proprietário mudou a estratégia para manter essa captura
somente no HD de 18 TB. A transferência ao Windows foi interrompida; os arquivos
parciais foram preservados, mas estão incompletos e **não servem como origem de
restauração**. O checkpoint anterior já verificado no Windows continua intacto,
com sua evidência histórica de restauração e ensaio dos 13 serviços.

O HD contém mídia e a única cópia completa do estado final; se ele falhar,
esse backup mais recente também pode ser perdido. A restauração integral do conjunto final
não foi testada. O proprietário optou por prosseguir com esses limites; concluir
a cópia Windows ou repetir o ensaio integral não é pré-requisito desta instalação.

| Evidência da captura final | Estado em 15/11 |
|---|---|
| Arquivos e recibo de captura | Selados; origem estável e checksums no HD confirmados |
| Recibo de controle no Windows | Copiado e conferido; não representa a transferência dos arquivos grandes |
| Transferência final ao Windows | Interrompida por decisão do proprietário; arquivos parciais preservados, incompletos e sem aceite para restauração |
| Restauração integral do conjunto final | Não testada; não será exigida antes de instalar conforme a decisão do proprietário; o ensaio anterior mantém seu alcance original |

## Estado da passagem física

A auditoria de **15/11, 21:24 UTC** confirmou backup montado, recibo e todos
os 36 containers parados. Às **21:32 UTC**, todos os HDs USB estavam ausentes,
antes do desligamento; o proprietário confirmou que havia desconectado todos
eles. O backup foi conferido antes da retirada, sem perda constatada. Às
**21:33 UTC**, após confirmar os containers parados
e concluir a sincronização, o host aceitou `systemctl poweroff`. SSH estava
inacessível às **21:33:48 UTC**; naquele momento o desligamento físico ainda não
havia sido observado. Em seguida, o proprietário instalou Proxmox.

O inventário SSH de **21:56:49 UTC** confirmou Proxmox no SSD autorizado,
segundo SSD ext4 desmontado com identidade preservada, HDs USB ausentes e rede
pelo adaptador Ethernet USB. O acesso com chave dedicada foi testado em sessão
separada; às **21:57:57 UTC**, HTTPS validado pela CA obtida no SSH respondeu
`200`. A entrega do host está concluída; o
[estado canônico](../implementation-status.md#host-proxmox-entregue) detalha as
provas e os limites. Não reconectar, montar ou reparar discos automaticamente.

## Preparação utilizada na instalação

Os itens abaixo preservam o roteiro da passagem concluída, sem exigir nova
instalação ou repetição das verificações já comprovadas. Operações futuras
devem manter a identificação por modelo/serial e o escopo dos discos.

| Item | Resultado necessário |
|---|---|
| Aplicações a retomar | Inicialização isolada examinada nos 13 serviços descritos acima; preservar imagens, dependências e manutenção e respeitar os limites do ensaio |
| Outro projeto do host | Incluído na captura final; sua restauração funcional não é comprovada pelo ensaio anterior de mídia |
| SSD de instalação | Sobrescrita autorizada somente para o SSD de sistema identificado na ficha privada, para instalar Proxmox; conferir modelo/serial no instalador |
| Segundo SSD e USBs | Conteúdo e papéis identificados; permanecem fora dos alvos de instalação; não criar espelho nem pool que os inclua |
| Rede de gestão | Proprietário confirmou que manterá o adaptador Ethernet USB e reservará o endereço combinado; conferir a reserva no roteador, ausência de conflito, NIC/MAC, IP/CIDR, gateway, DNS, hostname e alcance pelo Windows |
| Console físico | Proprietário disponível com tela/teclado e acesso ao boot; perda de SSH não elimina o acesso ao host |
| Backup final | Captura completa no HD de 18 TB selada e conferida por checksum, conforme a estratégia escolhida; preservar esse HD e o checkpoint anterior |

O inventário privado identificou ambos os SSDs de 512 GB, ocupados: um pelo
sistema, outro por mídia. Não há SSD vazio presumido. O proprietário confirmou
que manterá o adaptador Ethernet USB conectado durante a passagem e reservará
o endereço de gestão combinado. Essa confirmação ainda não é uma leitura da
configuração do roteador: a reserva e a ausência de conflito precisam ser
conferidas. Os valores de rede ficam na ficha privada. Nomes de
discos e interfaces podem mudar no novo sistema: selecionar discos por
modelo/serial e NIC por MAC, conforme a ficha privada.

O ensaio concluído não transforma todos os artefatos históricos em serviços
a reconstruir. A captura final contém estado posterior ao ensaiado, incluindo
o outro projeto e os volumes adicionais; seus checksums não comprovam uma
restauração funcional. Na reconstrução posterior, usar o procedimento já
validado e registrar os resultados reais. Não extrair
checkpoints sobre a instalação atual nem remover a manutenção para obter saúde
aparente. `production_ready` e `partial_restart_safe` permanecem falsos até os
respectivos aceites; instalação do host não os muda.

A ficha privada do operador reúne os valores reais acima, os recibos, o mapa
dos discos e os comandos específicos de conexão. Ela fica fora do Git. A
versão pública deste roteiro não contém IPs, seriais, fingerprints, chaves,
senhas ou caminhos privados.

## Mídia de instalação e chave do operador

O Intel i7 deste host exige a ISO **x86 de 64 bits (x86_64/amd64)**. ARM64 é
outra arquitetura e sua ISO não serve para este computador, mesmo que tenha
o mesmo número de versão. A [página oficial consultada em 15/11/2026](https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso/proxmox-ve-9-2-iso-installer)
publica a versão **Proxmox VE 9.2-1**, arquivo **`proxmox-ve_9.2-1.iso`**,
com SHA-256:

```text
4e88fe416df9b527624a175f24c9aa07c714d3332afb1ee3dbf3879573ef2c6c
```

**A ISO local no Windows foi verificada em 15/11/2026:** o arquivo tem
1.706.178.560 bytes e seu SHA-256 corresponde ao valor oficial acima. Tamanho
e data de modificação permaneceram estáveis durante a leitura; o recibo fica
privado. Se o arquivo for substituído ou alterado, repetir a comparação do
arquivo real com a [página oficial da ISO](https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso/proxmox-ve-9-2-iso-installer).

Gravação do pendrive e cada tela de boot não foram auditadas separadamente;
o proprietário concluiu a instalação e o novo host foi conferido por SSH.
Identificar separadamente o pendrive autorizado a receber a imagem; nunca
selecionar um disco do acervo. A documentação oferece Etcher ou
Rufus em modo DD para Windows. [Preparação oficial da mídia](https://github.com/proxmox/pve-docs/blob/master/pve-installation-media.adoc).
A ISO conferida fundamentou a preparação dessa mídia. A sobrescrita do SSD
específico foi autorizada, e a instalação nesse dispositivo foi conferida
posteriormente pelo inventário do host.

Uma chave SSH dedicada já foi preparada no Windows, sem substituir chaves
ou credenciais existentes. A chave privada permanece protegida no Windows;
somente a pública foi instalada no Proxmox. Seu fingerprint fica na ficha privada. O
arquivo `known_hosts` dessa nova conexão é separado do usado pelo Ubuntu.
Os caminhos e comandos concretos permanecem na ficha privada do operador.
[Chaves OpenSSH no Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).

## Passagem física e instalação

Procedimento preparado para a passagem já concluída. Ele não instrui reinstalar
o host entregue; eventuais novas operações destrutivas exigem escopo próprio.

1. Com as pendências anteriores fechadas, conferir que os projetos continuam
   parados e que o estado corresponde à captura aceita. Se houver retorno ou
   novas escritas, preservar e verificar esse estado antes de prosseguir.
   Preservar pausas, manutenção e estado da recuperação; não matar processos
   à força para acelerar a passagem.
2. Desligar o Ubuntu de forma limpa. A queda da sessão SSH não comprova que o
   desligamento terminou: conferir no console e no equipamento. Só depois
   desconectar os discos USB do acervo, inclusive o HD de 18 TB. **Manter o
   adaptador Ethernet USB conectado.** Não retirar fontes ou cabos de discos
   enquanto o servidor ainda estiver encerrando.
3. Conectar a mídia de instalação necessária e manter o adaptador Ethernet
   USB e a alimentação estáveis. O segundo SSD continua preservado; se sua desconexão
   física não fizer parte do procedimento acordado, conferir explicitamente
   que não foi selecionado pelo instalador. Não criar RAID/espelho entre os SSDs.
4. Iniciar o instalador interativo pelo console. Confrontar o SSD exibido com
   a identidade autorizada, sem confiar apenas em `/dev/sda`, ordem dos discos
   ou capacidade nominal. Conferir hostname, interface/MAC, IP/CIDR, gateway e
   DNS com a ficha privada. **Se o MAC do adaptador Ethernet USB esperado não
   aparecer ou a interface não tiver link, parar antes de `Install`** e resolver
   pelo console; não escolher outra interface por suposição. Definir a credencial inicial no console, sem
   registrá-la no Git ou na conversa.
5. Revisar o resumo e **desmarcar o reinício automático**. Se dispositivo ou
   escopo não corresponderem à autorização, voltar e resolver antes de clicar
   em `Install`. Esse clique inicia a formatação dos discos selecionados. Ao
   terminar, retirar a mídia e reiniciar manualmente com o proprietário presente.

O instalador apaga os discos selecionados e reinicia automaticamente por padrão;
a intervenção acima é intencional. A interface gráfica e a interface de texto
são opções do mesmo instalador. Não usar instalação automatizada para este
handoff. [Instalação oficial](https://github.com/proxmox/pve-docs/blob/master/pve-installation.adoc).

## Reconexão e entrega do host

No primeiro boot, manter os discos USB de mídia desconectados e o adaptador
Ethernet USB conectado. Pelo console físico,
conferir hostname, IP de gestão e fingerprint da chave de host SSH recém-gerada.
O fingerprint do host e o da chave do operador são identidades distintas;
registrar ambos na ficha privada.

No Windows, comparar a identidade apresentada com a obtida no console antes
de confiar nela. Usar o `known_hosts` dedicado; não desabilitar a verificação
de host nem apagar as entradas antigas do Ubuntu para contornar um alerta.
Instalar somente a chave pública do operador pelo caminho autenticado e testar
uma nova sessão SSH com ela, mantendo o console disponível.

Na sessão SSH autenticada, obter o fingerprint do certificado TLS com o
comando da ficha privada. Depois abrir o painel em `https://<IP-de-gestão>:8006`
e comparar essa identidade antes de confiar no certificado. Conferir horário,
hostname, rede, discos presentes e serviços do Proxmox. A gestão
inicial usa o usuário `root` no realm PAM. O acesso precisa funcionar sem
depender de core, Grafana ou uma VM ainda inexistente. [Acesso após instalação](https://github.com/proxmox/pve-docs/blob/master/pve-installation.adoc#accessing-the-management-interface-post-installation).

O certificado inicial é emitido pela CA própria da instalação; sua confiança
deve ser conferida pelo canal já autenticado, separadamente do SSH. Não abrir
portas administrativas no roteador nem ignorar a identidade TLS. [Certificados Proxmox](https://github.com/proxmox/pve-docs/blob/master/certificate-management.adoc).

A entrega desta fase, **host identificado e acessível pela rede privada**, foi
concluída. Ela não anexou USB, montou acervo, iniciou VMs ou publicou serviços.
A etapa seguinte prepara convidados, posse exclusiva do storage, restauração
funcional e isolamento conforme o [to-be](../architecture/to-be.md).

Se houver falha de rede, manter o console e diagnosticar a configuração real;
não reinstalar nem reiniciar em ciclo. Antes de `Install`, o Ubuntu preservado
pode continuar sendo o caminho de retorno. Depois de sobrescrever seu SSD,
retornar exige a restauração planejada; escolher outra entrada de boot não
recupera o sistema apagado. Os discos de origem e checkpoints permanecem intactos.
