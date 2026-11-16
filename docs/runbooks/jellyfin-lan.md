# Jellyfin na rede local

O endereço para a TV é **`http://192.168.1.20:8096`**, sem configurar um
prefixo no cliente. Essa entrada foi solicitada pelo proprietário para TVs
sem Tailscale. O nome privado `https://jellyfin.greis.dev.br/jellyfin/` continua
disponível pela tailnet. Não há publicação WAN nem alteração no roteador.

## Caminho e limites

O Proxmox encaminha somente TCP 8096 recebido em `vmbr0`, com origem
`192.168.1.0/24` e destino `192.168.1.20`, ao listener privado do controle.
A regra do firewall da VM 110 permite somente essa origem/porta. O Nginx
escuta no IP privado do controle e também aplica `allow` para essa rede e
`deny all` para as demais. Playback continua recebendo conexão do controle
pela regra existente; não foi liberada diretamente para a LAN.

O arquivo separado `/etc/nginx/sites-enabled/homelab-jellyfin-lan` encaminha
rotas raiz à BaseURL `/jellyfin/` internamente. Rotas já prefixadas continuam
funcionando. A BaseURL global do Jellyfin e os nove vhosts Tailscale não mudam.
Login, permissões, administração e logout continuam nativos do Jellyfin.
A compatibilidade de `api_key` legado fica limitada a socket e download de
item com GUID, na raiz ou sob `/jellyfin`, com as mesmas recusas de token
inválido, duplicado ou credencial explícita do ingresso privado. Não habilitar
autenticação legada global para resolver um cliente.

## Reaplicação

`scripts/render_lan_jellyfin.py` recebe JSON privado com `LAN_IP`, `LAN_CIDR`,
`CONTROL_IP` e `PLAYBACK_IP`, todos IPv4 RFC1918 literais; a sub-rede LAN deve
ter prefixo de pelo menos 24 bits. Ele gera somente a configuração Nginx e
o plano aditivo de rede. Não instala, reinicia ou altera rede por conta própria.

Antes de aplicar, guardar backups privados do include, do fragmento de bridge
existente e do firewall da VM. Instalar o include separado, executar `nginx -t`
e recarregar o Nginx existente. Inserir somente a regra `IN ACCEPT` gerada no
firewall da VM 110, preservando as demais regras, e validar com
`pve-firewall compile`.

A regra NAT contém o comentário `homelab-jellyfin-lan-8096`; verificar sua
presença com `iptables -C` antes de adicionar. Os hooks `post-up` e `pre-down`
gerados ficam no fragmento existente `/etc/network/interfaces.d/homelab-vmbr1`
e adicionam/removem somente essa regra. Não reiniciar interfaces para aplicar
a mudança. Não criar daemon ou unit do host, nem substituir o ruleset.

Para retirar a entrada, remover apenas a regra NAT exata, os dois hooks com
esse comentário, a exceção de entrada da VM 110 e o include LAN; validar e
recarregar o Nginx. Preservar configurações posteriores de outros componentes.

## Evidência de 16/11/2026

Pelo Windows na LAN, `/System/Info/Public` e `/web/index.html` responderam 200;
a raiz redirecionou para `web/`. `/Users` sem sessão respondeu 401. Logins de
conta comum e administradora tiveram identidade conferida, e as duas sessões
foram encerradas com revogação comprovada. A conta comum recebeu 403 em API
administrativa. Streaming Range e download legado retornaram 206, com leitura
limitada a 64 KiB. WebSocket legado e canônico retornaram 101 com aceite exato.

O teste automatizado usou o endereço raiz sem `/jellyfin`. Em seguida, o
proprietário confirmou que entrou e reproduziu pela TV nesse endereço LAN.
Os arquivos persistentes foram relidos: uma regra DNAT exata, dois hooks e
uma exceção de entrada na VM, com listener somente no IP privado do controle.
A porta 8096 pela tailnet foi recusada. Não houve teste de uma origem WAN
externa; o limite LAN foi conferido nas regras e nenhuma publicação no
roteador foi criada. Reboot do host não foi realizado neste aceite. Nenhuma
montagem, mídia, lease ou guarda de storage foi alterada. Recibos e backups
ficam somente na área privada.
