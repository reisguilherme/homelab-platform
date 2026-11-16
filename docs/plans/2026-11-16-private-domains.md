# Entrada HTTPS privada pelos domínios do homelab

> Execução: `superpowers:executing-plans`, com testes antes da implementação.

**Objetivo:** preparar os nove nomes privados em HTTPS na porta 443 do IP
Tailscale de `homelab-control` e aplicar a configuração após a emissão DNS-01
e integração do controle à tailnet autorizadas pelo proprietário.

**Arquitetura:** reutilizar Nginx no controle e registros DNS públicos apontando
para seu IP Tailscale. API e Grafana permanecem em loopback; Proxmox usa upstream
HTTPS com CA verificada, os Arr mantêm seus prefixos atuais no core e qBittorrent
usa exclusivamente o proxy administrativo na porta 18080. Jellyfin usa
controle → playback:8096 com `/jellyfin/` e autenticação nativa; sua publicação
WAN/10443 foi revogada pelo proprietário. A entrada
legada na porta 8443 permanece intacta até o corte explícito das origens.

**Tecnologias:** Nginx, Python 3.12, pytest, certificados ACME DNS-01.

**Desenho:** [domínios e acesso](../architecture/access-domains.md).

## Limites

- Nenhum segredo, IP Tailscale real ou certificado privado no Git.
- Renderer somente escreve um arquivo novo; não instala, reinicia ou aplica regras.
- Listener exige IPv4 Tailscale específico; sem `0.0.0.0`, IPv6 ou porta pública.
- Manter autenticação, CSRF e destino fixo por hostname; não registrar tokens.
- Preservar `infrastructure/control/nginx.conf` e seus acessos pela porta 8443.
- Manter `/radarr/`, `/sonarr/`, `/bazarr/` e `/prowlarr/`; Grafana nova usa a raiz do hostname.
- qBittorrent usa a raiz do hostname, preservando Host/Origin/Referer/cookies.
- Jellyfin usa `/jellyfin/`, inclusive no backend; preservar Range, Upgrade,
  autenticação nativa e mídia RO. Não aplicar o guard público nessa rota privada.
- Preparação local não comprova acesso real; registrar o aceite do servidor
  separadamente, sem confundir HTTP/TLS com fluxos autenticados completos.

## Entrega e validação

Arquivos novos: `infrastructure/control/private-domains.nginx.conf.template`,
`scripts/render_private_ingress.py`, `tests/test_private_ingress.py` e
`docs/runbooks/private-domains.md`. A fixture Nginx isolada fica em
`tests/test_private_ingress_nginx.py`; Compose e `.env.example` recebem somente
o parâmetro de subpath da Grafana, preservando o default antigo.

- [x] Escrever fixtures temporárias que recusem IP fora da tailnet, upstream
  público, caracteres de configuração em campos, paths relativos e sobrescrita.
  Rodar o teste e conferir falha por implementação ausente.
- [x] Implementar `render(config: dict) -> str` e CLI com JSON privado de entrada
  e arquivo novo de saída; validar todos os campos antes de escrever.
- [x] Criar template com hosts fixos, TLS e backends mínimos; recusar host/SNI
  incorreto, preservar prefixos Arr, WebSocket e upload do Proxmox, sem logs
  contendo query strings ou headers de autenticação.
- [x] Verificar os testes, Ruff e sintaxe Nginx com certificados de fixture
  quando Nginx estiver disponível; executar a suíte do projeto no Linux/WSL.
- [x] Documentar valores de origem/Grafana, entrega de certificados, ativação
  coordenada, testes reais e retorno à configuração anterior.

## Foco da revisão

1. Configuração injetada via JSON deve ser recusada antes de criar a saída.
2. Host desconhecido ou SNI diferente não pode alcançar um backend privado.
3. Prefixos Arr não podem desaparecer ou ser duplicados no proxy.
4. Proxmox deve verificar CA/nome TLS e manter console/upload funcionais.
5. A mudança de origem da API/Grafana é um corte explícito; preservar o listener
   antigo não significa que duas origens de autenticação sejam aceitas ao mesmo tempo.

## Registro

O proprietário autorizou a implementação; a preparação local não executou
SSH nem deploy. Depois da revisão, a coordenação aplicou a configuração no
servidor e registrou os aceites abaixo. Commit/push pertencem à coordenação.
Prowlarr e qBittorrent foram acrescentados pelo proprietário durante a execução;
o renderer mantém destinos fixos, sem permitir a porta nativa qBit na WAN.

Verificação final em Linux/WSL, Python 3.12.3: 478 testes passaram e um foi ignorado por
ausência do `promtool` e de sua imagem fixada. Os cenários com Nginx em
container isolado passaram; não usaram serviços reais. Ruff, formatação dos 29 arquivos e
validação do Compose passaram. A fixture verificou encaminhamento do header
Upgrade, sem comprovar uma sessão real do console Proxmox.

Implantação posterior no mesmo dia: certificado wildcard Let's Encrypt emitido
por DNS-01 manual no Registro.br; oito vhosts responderam HTTP 200 com cadeia
válida localmente e pelo Windows/Tailscale usando DNS normal. 443 foi admitida
e 22, 8006, 8443, 8080, 3080, 9090 e 9100 foram negadas por esse caminho. qBit
anônimo retornou 403; Host/SNI divergentes retornaram 421. Somente `control`
e `grafana` foram recriados, com healthchecks válidos e site legado 8443
preservado. O helper privado teve quatro fixtures Linux aprovadas, incluindo
retorno de arquivos/symlinks e preservação da ordem dos prestarts.

Sete checks reais qBit passaram: 403 anônimo, login/versão, 401 para Origin
incorreto mesmo com Referer correto, sessão preservada e logout seguido de 403.
O restart real do Nginx passou com espera do IP antes de `nginx -t` e HTTP 200
após o retorno. A edge permaneceu bloqueada para controle:443,
core:7878/18080 e PVE:8006/22. As métricas dos certificados público/privado e
alertas de 21/7 dias por 5 minutos foram carregados saudáveis, somente no painel.
Depois, o proprietário revogou WAN/VPS/10443 e criou o A de Jellyfin para o
controle Tailscale. O renderer recebeu `PLAYBACK_IP` obrigatório e nono vhost;
44 testes focados passaram, incluindo Range 206 com bytes de fixture, headers
de autenticação e Upgrade. Os três containers públicos foram parados e WAN
recusada; dois DNAT ativos, quatro hooks persistentes e três exceções dos
guests foram removidos com convergência do firewall conferida. Acesso
controle/playback, SSH, NFS e masquerade foram preservados. Os nove nomes
responderam HTTP 200 com TLS válido; Jellyfin passou DNS normal no Windows,
logins comum/admin e identidades, negação administrativa 403 à conta comum,
catálogo de vídeo, Range 206 de 64 KiB e WebSocket 101 com aceite exato.
O teste inicial usou `ApiKey` canônico, sem habilitar APIs legadas. A inspeção
do bundle instalado confirmou dois usos antigos de `api_key`: socket e
download. Foi implantado um adapter somente nessas rotas, com token único
validado, precedência de credenciais explícitas e recusa de nomes de query
codificados para evitar ambiguidade. Os 72 testes focados passaram, incluindo
token malformado, duplicado, conflito com auth moderna, escopo por rota/host
e valores codificados preservados. O caso de nome codificado falhou antes
da correção e passou depois. No aceite real final, WebSocket legado e
canônico retornaram 101 com aceite exato; download legado retornou 206 de
64 KiB. Os nove vhosts mantiveram HTTP 200 com TLS válido. Logout revogou as
duas sessões. Reprodução interativa completa em cliente segue pendente.
O wildcard privado cobre os nove nomes. O certificado público foi retirado
de uso, com chaves preservadas privadamente e métrica desativada.
Não houve reboot de VM. Posteriormente, por autorização explícita, a VM edge
(122) foi desligada de forma limpa em cerca de seis segundos e conferida
como `stopped`, com `onboot` alterado de 1 para 0. Não houve parada forçada;
discos e demais configurações foram preservados. Após o desligamento, os
nove domínios mantiveram HTTP 200 e TLS válido pelo Windows/Tailscale com
DNS normal; 443 permaneceu aberta e as portas administrativas verificadas,
fechadas. Os acessos privados não dependem da edge.
Grants por usuário, console/upload Proxmox e
automação de renovação DNS-01 permanecem pendentes. DDNS residencial deixou
de ser necessário. Não houve migração de DNS
para Cloudflare nem alteração da política da conta Tailscale.
