# Serviços privados por Tailscale

## Extensão Seerr — 16/11/2026

O proprietário adicionou `overseer.greis.dev.br` (grafia escolhida por ele).
Esse décimo nome aponta para o mesmo IP Tailscale do controle e usa o
certificado wildcard existente. O include opcional
[`seerr-private.nginx.conf.template`](../../infrastructure/control/seerr-private.nginx.conf.template)
encaminha à porta 5055 do core, com hostname/SNI fixos e protocolo HTTPS
informado ao aplicativo. Aplicar somente as duas permissões correspondentes
no firewall: saída do controle e entrada do core para esse destino/porta.
Não abrir a porta no roteador nem publicar a interface nativa na WAN.

O aceite real conferiu login via Jellyfin na mesma conta administrativa,
consulta autenticada, logout e recusa após logout; cookies de sessão usam
Secure e HttpOnly. Host/SNI divergente retornou 421. Os nove nomes anteriores
continuaram respondendo 200 com TLS válido; a entrada Jellyfin LAN permaneceu
disponível. O catálogo operacional do core fornece esse endereço ao card Seerr.
Os relatos das nove entradas abaixo descrevem a implantação anterior.

## Implantação das nove entradas anteriores

Jellyfin também possui a entrada LAN **`http://192.168.1.20:8096`**, autorizada
para TVs sem Tailscale. Ela usa listener e regras separados, conforme o
[runbook LAN](jellyfin-lan.md). Os nove nomes deste documento continuam pela
tailnet; a exceção LAN não publica serviços na WAN.

O desenho atual concentra os nove nomes privados no Nginx de `homelab-control`, conforme
[domínios e acesso](../architecture/access-domains.md). A implantação em
16/11/2026 usou Certbot/DNS-01 com TXT manual no Registro.br, sem Cloudflare.
Oito páginas responderam HTTP 200 com TLS válido pelo Windows/Tailscale e DNS
normal; API qBit anônima retornou 403 e Host/SNI divergentes, 421. Sete checks
reais qBit passaram, incluindo login/versão, Origin incorreto 401 mesmo com
Referer correto, preservação da sessão e logout seguido de API 403. O caminho
Tailscale admitiu 443 e negou 22, 8006, 8443, 8080, 3080, 9090 e 9100.

Este procedimento registra a configuração e sua reaplicação controlada.
Renovação DNS-01 ainda exige intervenção; DDNS residencial não é necessário.
Grants por usuário,
console/upload Proxmox e retorno após reboot de VM não foram encerrados por
esses testes. O restart real do Nginx passou com espera de IP antes de
`nginx -t` e HTTP 200 depois; a edge permaneceu bloqueada para controle:443,
core:7878/18080 e PVE:8006/22.

O proprietário acrescentou `jellyfin.greis.dev.br` e revogou a publicação
WAN/10443. O A aponta para o controle Tailscale; o nono vhost foi implantado
para `/jellyfin/`, com redirecionamento da raiz e backend direto playback:8096.
O wildcard privado existente cobre esse nome. A autenticação e administração
são nativas do Jellyfin dentro da tailnet; essa rota não usa o guard da edge.
Mídia permanece RO. TLS/DNS, logins comum e administrador, identidades,
catálogo de vídeo, Range 206 de 64 KiB e WebSocket 101 com aceite exato passaram.
A conta comum foi recusada na rota administrativa com 403. O teste WebSocket
usou `ApiKey` canônico; `api_key` legado está desabilitado no Jellyfin 12 e
não foi habilitado para contornar o teste. O bundle web instalado ainda usa
`api_key` no socket e no download; a adaptação de compatibilidade descrita
abaixo foi implantada. No aceite real final, WebSocket legado e canônico
retornaram 101 com aceite exato; download legado retornou 206 de 64 KiB.
Logout revogou as duas sessões.
Reprodução interativa completa em cliente ainda não foi aceita.
Os três containers públicos estão parados; dois DNAT ativos, quatro hooks
persistentes e três exceções dos guests foram removidos, com convergência do
firewall e preservação de controle/playback, SSH, NFS e masquerade conferidas.
A VM edge (122) foi desligada de forma limpa, sem parada forçada, e seu
estado `stopped` foi confirmado. `onboot=0` evita retorno automático; discos
e demais configurações foram preservados. Os nove domínios mantiveram
HTTP 200 e TLS válido pelo Windows/Tailscale depois do desligamento.
Não ligar essa VM para atender os nomes privados: o caminho direto pelo
controle já os atende.

## Compatibilidade do cliente Jellyfin 12

O Nginx adapta `api_key` somente em `/jellyfin/socket` e
`/jellyfin/Items/<GUID>/Download`, com GUID de 32 caracteres hexadecimais ou
formato de 36 caracteres com hífens. Imagens, streaming e outros hosts não
recebem essa adaptação. O servidor mantém `EnableLegacyAuthorization`
desabilitado e valida normalmente a sessão e suas permissões.

Um token legado único, de 1 a 4.096 caracteres em `[A-Za-z0-9._~-]`, vira
`Authorization: MediaBrowser Token="..."` somente na ausência de headers de
autenticação não vazios e de `ApiKey` canônico, mesmo quando este está vazio.
Authorization, X-Emby-Authorization, X-Emby-Token e X-MediaBrowser-Token
explícitos impedem esse fallback, inclusive quando inválidos. Na adaptação
elegível, token inválido, duplicado ou nome de parâmetro percent-encoded
retorna 400. A última restrição evita divergência entre nomes brutos no
Nginx e nomes decodificados pelo Jellyfin; valores codificados de parâmetros
como `deviceId` continuam permitidos. Não ampliar o escopo nem habilitar
autenticação legada global para resolver outro cliente.

## Preparar configuração e certificados

A edge está desligada por decisão do proprietário, com início automático
desativado. Seu target de exporter foi retirado individualmente do `file_sd`
de guests, com backup privado. A regra geral de indisponibilidade e os demais
targets permanecem ativos; não silenciar alertas de outros convidados. Se a
VM voltar a ter uma função aprovada, readmitir também seu target depois de
conferir o exporter. O proxy privado atual não depende dessa VM.

O renderer exige um JSON privado, fora do Git. Exemplo com valores fictícios:

```json
{
  "TAILSCALE_IP": "100.64.20.30",
  "CORE_IP": "172.28.70.10",
  "PLAYBACK_IP": "172.28.70.11",
  "PVE_IP": "192.168.77.20",
  "PVE_TLS_NAME": "pve-fixture.example.test",
  "TLS_CERT_PATH": "/etc/homelab-control/tls/private/fullchain.pem",
  "TLS_KEY_PATH": "/etc/homelab-control/tls/private/privkey.pem",
  "PVE_CA_PATH": "/etc/homelab-control/tls/pve-ca.crt"
}
```

Usar o IPv4 realmente atribuído ao controle pelo Tailscale; o renderer recusa
endereços fora da faixa da tailnet, `0.0.0.0` e o endereço do resolvedor interno
Tailscale. Isso valida o formato, não prova posse ou permissão desse IP.
Confirmar o nome TLS do Proxmox contra seu certificado e usar a CA já confiável.
Nunca contornar falha de certificado com `proxy_ssl_verify off`.

O certificado privado precisa cobrir estes nove nomes por SAN ou wildcard:

```text
homelab.greis.dev.br
grafana.greis.dev.br
proxmox.greis.dev.br
radarr.greis.dev.br
sonarr.greis.dev.br
bazarr.greis.dev.br
prowlarr.greis.dev.br
qbittorrent.greis.dev.br
jellyfin.greis.dev.br
```

Entregar fullchain e chave por caminho privado controlado, conferindo validade,
nomes e correspondência da chave. Manter a chave acessível somente a root; o
master Nginx carrega os arquivos antes de reduzir privilégios. Não compartilhar
a chave privada administrativa com a edge pública. DNS-01 manual exige nova
intervenção nas renovações; instalar Certbot sozinho não as automatiza.
Na implantação, o diretório de entrega no controle recebeu modo 0700 e os
PEMs, 0600, pertencentes a root. Conferir também a cadeia intermediária e o
prazo restante antes de substituir arquivos ou recarregar Nginx.

Gerar sempre um arquivo novo:

```bash
python3 -B scripts/render_private_ingress.py \
  --config /private/private-ingress.json \
  --output /private/private-domains.nginx.conf
```

O comando não altera o Nginx, não cria diretórios e recusa sobrescrita. O
template é um include de `http {}` para `sites-enabled`, ao lado do site
atual na porta 8443. Não substituir o arquivo global `nginx.conf` por ele.
Os backends são fixos: API/Grafana em loopback, Proxmox HTTPS na porta 8006,
core nas portas 7878, 8989, 6767 e 9696, e proxy administrativo qBit na porta
18080, além da playback:8096 para Jellyfin. `PLAYBACK_IP` é obrigatório e
precisa ser IPv4 RFC1918 literal. Jellyfin preserva `/jellyfin/`, headers de
autenticação, Range e Upgrade; caminhos fora desse prefixo retornam 404.
Não há proxy genérico para URLs do cliente.

## Filtro Tailscale e inicialização

O convidado mantém a tabela própria `inet homelab_private`, sem limpar o
ruleset do host ou alterar as tabelas geridas pelo Tailscale. O contrato abaixo
usa um placeholder: substituir `IP_TAILSCALE_DO_CONTROL` pelo IPv4 atribuído
antes de validar qualquer arquivo com `nft -c -f`. Não executar o bloco literal.

```nft
define control_tail_ipv4 = IP_TAILSCALE_DO_CONTROL

table inet homelab_private {
    chain input {
        type filter hook input priority -20; policy accept;
        iifname "tailscale0" ip daddr $control_tail_ipv4 tcp dport 443 accept
        iifname "tailscale0" drop
    }
    chain forward {
        type filter hook forward priority -20; policy accept;
        iifname "tailscale0" drop
    }
}
```

As regras abrangem entrada/encaminhamento pela interface `tailscale0`,
inclusive negação do restante em IPv6; não modificam loopback ou a interface
de gestão. A política `accept` dessa tabela para outras interfaces não
substitui os demais filtros existentes. O listener Nginx também exige o IPv4
específico e recusa nomes desconhecidos. `shields-up=false` só foi aplicado
depois do filtro. Não habilitar Tailscale SSH, exit node ou anúncios de sub-rede
como parte deste procedimento.

O arquivo operacional é `/etc/homelab-control/tailscale-https.nft`; o drop-in
de `tailscaled.service` o carrega antes do daemon:

```ini
[Service]
ExecStartPre=/usr/sbin/nft -f /etc/homelab-control/tailscale-https.nft
```

Reaplicação precisa substituir somente a tabela própria de maneira atômica e
idempotente, sem acumular regras nem executar `flush ruleset`. Preservar outros
prestarts da unit e conferir o arquivo real antes de uma alteração.

Nginx tem `Wants=tailscaled.service` e `After=tailscaled.service`. Como a unit
ativa não garante que o IP já esteja na interface, o prestart
`/usr/bin/python3 /etc/homelab-control/wait-tailscale-ip.py` consulta os endereços
IPv4 de `tailscale0` por até 45 segundos, aguardando o IP esperado. Falha sem
fallback se ele não aparecer. O drop-in recompõe a lista `ExecStartPre` com
essa espera **antes de todos os prechecks originais**, incluindo `nginx -t`;
não basta acrescentá-la depois do teste de configuração. Mantém
`Restart=on-failure` e `RestartSec=5s`. Não habilitar `ip_nonlocal_bind` no guest.

O ordenamento foi instalado sem reiniciar Tailscale. O restart real do Nginx
conferiu a ordem espera de IP → `nginx -t` e o retorno HTTP 200. Não houve
reboot de VM nesta etapa: conferir persistência e retorno completo exige um
ensaio posterior e recibo próprio. As regras de grants da conta permanecem
separadas desse filtro local.

## Alerta de expiração dos certificados

Após a retirada da publicação WAN, permanece ativa no controle a métrica
`homelab_tls_certificate_not_after_seconds`, com `certificate="private"`,
pelo textfile collector existente. O certificado público foi retirado de uso,
com chaves preservadas privadamente e métrica `streaming` desativada. Prometheus
carregou as duas regras de `deploy/observability/rules/tls.yml`, com saúde `ok`.
`promtool check rules` e `promtool check config` passaram; a recarga por HUP
preservou o container e seu horário de início. Nenhum timer foi criado.

O aviso dispara quando restam menos de 21 dias; abaixo de 7 dias, inclusive
depois do vencimento, passa a crítico. Ambos exigem a condição por 5 minutos.
As expressões subtraem `time()` da data absoluta de expiração, portanto a
contagem continua avançando sem executar o script diariamente. Os alertas
ficam no painel; não foi configurado envio externo.

Após cada renovação, entregar o certificado e a chave ao proxy correto,
validar/recarregar o proxy e executar novamente o exportador **nessa VM**:

```bash
# No controle, após entregar o certificado dos serviços privados:
sudo python3 /usr/local/libexec/export_tls_expiry.py \
  --certificate-label private \
  --certificate /etc/homelab-control/tls/private/fullchain.pem \
  --output /var/lib/prometheus/node-exporter/homelab-tls-private.prom
```

O script lê apenas o PEM público e substitui o textfile atomicamente, com
modo `0644`; erro preserva a métrica anterior. A coleta mede o certificado
implantado no arquivo indicado, não prova qual certificado o processo mantém
em memória. Conferir HTTPS depois da recarga e as séries no Prometheus.
Este alerta não automatiza DNS-01, entrega ou renovação. Apagar o textfile
do certificado privado ativo também elimina sua série e precisa de investigação.
DDNS residencial não é necessário para os nomes Tailscale do desenho atual.

## Preparar acesso e origens

1. Associar o controle à tailnet e conferir identidade, IP e grants. Permitir
   aos administradores somente a porta 443 desse destino; manter Tailscale
   SSH, exit node e anúncios de sub-rede desativados se não fazem parte de uma
   decisão separada. Verificar o firewall do guest e as regras do Proxmox.
2. Permitir do controle apenas os quatro backends Arr e o proxy administrativo
   qBit no core, playback:8096 e o HTTPS do Proxmox já autorizado.
   Não liberar toda a rede dos convidados.
3. Criar registros A dos nove nomes para o IP Tailscale do controle, sem proxy
   público/CDN. Não reativar streaming público ou redirecionamento 10443. Essa configuração
   exige Tailscale ativo no cliente inclusive na LAN.
4. Conferir que certificados e IP Tailscale existem, validar com `nginx -t`
   e só então ativar o include/recarregar Nginx. Testar os nomes com resolução
   local explícita antes de depender da propagação DNS, se necessário.
5. Fazer o corte de origem da aplicação com backup privado dos valores antigos:

| Configuração privada | Valor novo |
|---|---|
| `PLATFORM_ORIGIN` | `https://homelab.greis.dev.br` |
| `PVE_WEB_URL` | `https://proxmox.greis.dev.br` |
| `GRAFANA_URL` | `https://grafana.greis.dev.br/` |
| `HOMELAB_GRAFANA_ROOT_URL` | `https://grafana.greis.dev.br/` |
| `HOMELAB_GRAFANA_SERVE_FROM_SUB_PATH` | `false` |

API e Grafana continuam com portas publicadas somente em loopback. Recriar
apenas esses serviços para aplicar o ambiente; reiniciar a API invalida as
sessões em memória. O default de subpath da Grafana continua `true` para os
destinos anteriores. Na nova origem ela usa `/`, não `/grafana/`.

Os Arr preservam a configuração existente: a raiz de cada hostname redireciona
para `/radarr/`, `/sonarr/`, `/bazarr/` ou `/prowlarr/`, sem reescrever banco ou integração
entre serviços. Os cookies e a autenticação continuam sob responsabilidade
da aplicação. Nginx preserva `Origin` e substitui os headers encaminhados por
valores canônicos; IPs alegados em `X-Forwarded-For` do cliente não são aceitos.
qBittorrent usa a raiz de seu hostname pelo proxy privado `qbit-monitor`, na
porta 18080 do core. Host, Origin, Referer e cookies seguem sem reescrita;
autenticação e CSRF continuam nativos, e nenhuma porta nativa é publicada na WAN.

Manter o site antigo na porta 8443 facilita o retorno operacional, mas a API
aceita uma única `PLATFORM_ORIGIN`. Depois do corte, o endereço antigo não é
uma segunda origem de login autorizada; o mesmo vale para a URL canônica da
Grafana. Não prometer dois acessos autenticados equivalentes.

## Aceite e retorno

O corte das origens documentadas já foi aplicado, com backup privado e recarga
validada do Nginx. Somente `control` e `grafana` foram recriados; healthchecks
passaram. O site legado 8443 permaneceu intacto. Os aceites que dependem de
sessões humanas não se encerram com o smoke HTTP/TLS. A rodada qBit posterior
aprovou os sete checks de autenticação/CSRF; preservar a distinção entre 401
por Origin inválido e 403 por ausência de sessão ao repetir o procedimento:

- Conferir listener somente no IP Tailscale, certificados e hostname/SNI
  desconhecido recusado. Não publicar portas administrativas no roteador.
- Testar os nove nomes em um cliente autorizado, incluindo login/logout e
  operação com CSRF na plataforma, login Grafana, navegação Arr e console
  WebSocket do Proxmox e login/CSRF do qBittorrent. O proxy permite upload de
  até 32 GiB no Proxmox sem
  armazenar o corpo integral na VM de controle; validar um upload descartável
  no storage aprovado antes de declarar essa função aceita.
- No Jellyfin, conferir login/logout, catálogo, Range, WebSocket e reprodução
  pelo novo nome privado; administração depende do papel nativo da conta.
  Testes de headers em fixture não substituem reprodução em cliente real.
- Confirmar negação a outro usuário sem grant e a cliente sem Tailscale,
  além das negações existentes de edge/playback à gestão. O DNS público revela
  os nomes, mas não concede acesso. Grants de rede para um IP/porta compartilhado
  não diferenciam os nove nomes; cada aplicação mantém sua autenticação.
- Testar expiração/renovação e recarga dos certificados com o método escolhido.
  Nginx testa sintaxe, existência e leitura dos arquivos; isso não substitui
  conferir confiança, SAN, prazo e acesso externo real.
- Acesso e erros deste include não geram logs brutos de requisições, para evitar
  gravar credenciais presentes em URLs. A auditoria autenticada da plataforma
  permanece; diagnósticos específicos devem usar recibos privados sem tokens.

Para retornar, restaurar os valores privados de origem/Grafana e recriar só
os serviços alterados. Remover apenas o include novo após `nginx -t`, mantendo
o site antigo e o acesso SSH de gestão. Reverter registros/grants somente se
for necessário, sem apagar identidade ou chaves de outros nós da tailnet.

Os testes locais usam fixtures e não comprovam grants, rede, certificados ou
aplicações reais. Registrar os aceites do servidor separadamente no
[estado de implementação](../implementation-status.md).
