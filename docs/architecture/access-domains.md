# Domínios e acesso ao homelab

**Nova informação do proprietário — 16/11/2026:** a operadora informou que
não libera as portas nem IP fixo para cliente pessoa física. A orientação
passou a ser avaliar acesso sem entrada pela conexão residencial: Jellyfin
público e administração por Tailscale. Isso substitui a espera por liberação
de 80/443 como próximo passo; nenhum novo túnel ou DNS foi aplicado.

O Tunnel público padrão da Cloudflare não é a recomendação para transportar
o vídeo do Jellyfin. A [documentação de roteamento](https://developers.cloudflare.com/tunnel/concepts/routing/)
explicita que hostnames públicos nos planos Free, Pro e Business exigem um
serviço pago específico para vídeo e arquivos grandes. A
[política de vídeo](https://developers.cloudflare.com/fundamentals/reference/policies-compliances/delivering-videos-with-cloudflare/)
distingue esse caso das rotas privadas. Desativar cache não transforma uma
rota pública em privada.

**Alternativa proposta, ainda sem contratação ou implantação:** VPS com HTTPS
para `streaming.greis.dev.br`, encaminhando por túnel WireGuard para a entrada
pública restrita da edge. A edge inicia o túnel de saída; a VPS não recebe
rota para administração, core, Proxmox ou storage. Preservar o guard público
do Jellyfin. O DNS pode continuar no Registro.br; se for migrado para
Cloudflare, esse nome deve usar somente DNS, sem proxy de vídeo.

Os nomes administrativos seguem pela entrada privada, com Tailscale, regras
de acesso mínimas e DNS interno. A aceitação de uma VPS com mensalidade está
pendente. A alternativa sem VPS é tornar também o Jellyfin privado, com
clientes autorizados na VPN, conferindo suporte dos aparelhos e limites do
plano antes de adotar. Nenhuma opção elimina o limite do upload residencial;
a VPS adiciona custo de tráfego e deve ser dimensionada pelo uso de streaming.

### Diagnóstico anterior à resposta da operadora

**Atualização em 16/11/2026:** backend edge → playback e isolamento de rede
comprovados; 33 checks do proxy passaram, incluindo login comum e negações admin.
DNAT TCP 80/443 aplicado sem reload e HTTP 308 para HTTPS correto pela LAN.
DNS A, WAN e vínculo dos mapeamentos foram conferidos; NAT loopback HTTP funciona
no desktop. **Ainda não há certificado TLS**; ACME e 4G nas portas externas
80/443 deram timeout. A regra temporária WAN 10443 → LAN 443 foi criada: o teste
4G deu erro de protocolo SSL e a captura validada registrou oito SYN externos
distintos chegando a PVE:443. A porta alternativa chega ao mesmo destino interno;
isso ainda não distingue roteador de operadora na falha de 80/443.
O proprietário escolheu resolver **80/443 e a URL sem porta** primeiro. 10443
é somente diagnóstico temporário ativo; não preparar DNS-01 ou 10443 em produção.
Consulta RO: firewall Off, proteção contra ataques Enable, controle parental
desmarcado e tabela IP Filter vazia; Access Control não aparece na UI. O próximo
passo é suporte Brava conferir filtro/reserva de 80/443 no equipamento ou a montante.
Auditoria de 15/10 já registrava timeout externo 80/443 e resposta em 54443.
O proxy antigo era TV box Armbian na mesma LAN, com WAN 54443 → LAN 443 e DNS-01;
em 18/10 houve HTTP 200 externo/TLS válido nessa porta alta. A falha padrão
precede a migração, mas ainda não comprova responsabilidade da operadora.
`streaming.greis.dev.br` permanece em ativação, sem anúncio de disponibilidade.
Não se declara implantação dos nomes administrativos privados.

Desenho solicitado em **16/11/2026**, em implantação parcial. O proprietário possui
`greis.dev.br` e definiu Jellyfin público autenticado e administração pela LAN ou
Tailscale. Este documento registra os nomes e as fronteiras; não aplica DNS,
certificados, proxy, ACLs ou regras de roteador. A prioridade continua sendo
[concluir o core e consolidar a mídia no HD de 18 TB](operational-priorities-2026-11-16.md).

## Nomes solicitados

Todos os destinos abaixo são o desenho desejado para os novos nomes. Um serviço
já responder por seu endereço atual não comprova que o domínio esteja operante.

| Nome | Aplicação | Acesso desejado | Caminho proposto |
|---|---|---|---|
| `streaming.greis.dev.br` | Jellyfin | Público, com autenticação da aplicação | Proxy público na edge → Jellyfin na playback |
| `radarr.greis.dev.br` | Radarr | LAN/Tailscale | Entrada administrativa privada → aplicação no core |
| `sonarr.greis.dev.br` | Sonarr | LAN/Tailscale | Entrada administrativa privada → aplicação no core |
| `bazarr.greis.dev.br` | Bazarr | LAN/Tailscale | Entrada administrativa privada → aplicação no core |
| `proxmox.greis.dev.br` | Console/API Proxmox | LAN/Tailscale | Entrada de gestão privada → Proxmox |
| `grafana.greis.dev.br` | Grafana | LAN/Tailscale | Entrada de gestão privada → Grafana no homelab-control |
| `homelab.greis.dev.br` | Portal e API da plataforma | LAN/Tailscale | Entrada de gestão privada → portal/API no homelab-control, na mesma origem |

Os nomes opcionais abaixo são propostas adicionais, sem confirmação de adoção:

| Nome opcional | Aplicação | Limite proposto |
|---|---|---|
| `qbittorrent.greis.dev.br` | Administração qBittorrent | Privado, pelo proxy administrativo; não publicar a porta administrativa nativa na WAN |
| `seerr.greis.dev.br` | Seerr | Privado na LAN/Tailscale; acesso público exigiria uma decisão própria |

## Separação das entradas

```mermaid
flowchart LR
    INTERNET[Internet] --> EDGE[Proxy público na edge]
    EDGE --> JELLYFIN[Jellyfin na playback]
    ADMIN[LAN autorizada / Tailscale] --> PRIVATE[Entrada administrativa privada]
    PRIVATE --> CORE[Aplicações administrativas no core]
    PRIVATE --> CONTROL[Portal / API / Grafana no controle]
    PRIVATE --> PVE[Gestão Proxmox]
```

O diagrama distingue o destino desejado do backend já aceito; não comprova
publicação externa nem implantação dos nomes privados. O
proxy público recebe somente a rota de Jellyfin. Não recebe rotas administrativas,
credenciais Proxmox, bancos de controle ou mounts de mídia. As entradas privadas
devem continuar acessíveis aos administradores sem depender do proxy público.
A localização dos proxies privados e suas permissões serão detalhadas conforme
as [fronteiras da plataforma](operations.md) e dos consumidores.

A administração do próprio Jellyfin também permanece privada. A rota
`streaming` deve cumprir o contrato público do consumidor e negar operações
administrativas, inclusive para uma sessão com privilégios elevados. Não basta
ocultar links da interface ou dar outro nome DNS ao mesmo backend. O aceite
deve conferir a reprodução pública e essas negações separadamente; exclusões
continuam sujeitas à autoridade independente do core descrita no
[to-be](to-be.md).

DNS informa o destino, TLS autentica o servidor e protege o transporte, e a
autenticação da aplicação identifica quem pode usá-la. Um domínio próprio e um
certificado válido não autorizam usuários nem fecham portas. As sessões, TOTP,
CSRF e ACLs existentes precisam continuar funcionando com a nova origem; a LAN
também precisa de restrições de gestão. O acesso Tailscale exige política efetiva
e testes de permissão/negação, ainda sem evidência para estes nomes.

## DNS e certificados

A consulta pública somente leitura realizada pela coordenação em 16/11/2026
retornou `a.auto.dns.br` e `b.auto.dns.br` como servidores autoritativos de
`greis.dev.br`, correspondentes ao DNS do Registro.br. Isso não comprova acesso
à conta, disponibilidade de API, integração de renovação ou registros dos sete
serviços. Não se presume Cloudflare nem outro provedor de automação.

A proposta é resolver os nomes administrativos para destinos privados na LAN
e na tailnet, usando DNS interno e, quando necessário, um resolvedor restrito
para `greis.dev.br` no Tailscale. Esse resolvedor deve preservar a resolução de
`streaming.greis.dev.br` e dos demais registros existentes. MagicDNS não permite
adicionar registros arbitrários; um resolvedor privado também precisa estar
alcançável pelos clientes autorizados. A escolha entre endereço Tailscale do
resolvedor e uma rota restrita continua pendente. Ver
[DNS no Tailscale](https://tailscale.com/docs/reference/dns-in-tailscale).

O HTTPS nativo do Tailscale emite certificados para nomes de dispositivos sob
o domínio da tailnet em `ts.net`; isso não emite automaticamente certificados
para `greis.dev.br`. Os nomes solicitados precisam de sua própria emissão e
renovação. Certificados públicos podem revelar nomes em Certificate Transparency,
mesmo quando os serviços são privados. Ver
[certificados HTTPS do Tailscale](https://tailscale.com/docs/how-to/set-up-https-certificates).

Para os serviços privados, a proposta é ACME DNS-01: provar controle do domínio
por TXT em `_acme-challenge`, sem expor portas administrativas à internet. A
renovação deve usar credenciais limitadas à validação necessária, mantidas fora
do Git; evitar entregar credencial ampla da zona ao proxy público. A validação
pode ocorrer separadamente, com entrega controlada dos certificados. Delegação
por CNAME ou NS permite responder ao desafio em outra zona. Ver
[desafios do Let's Encrypt](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge).

A estratégia de automação ainda precisa ser escolhida conforme os recursos
reais da conta DNS:

- Manter o DNS autoritativo atual e delegar os nomes de desafio necessários
  para uma zona com API adequada, limitando as credenciais à validação.
- Migrar o DNS autoritativo para um provedor com automação compatível, após
  inventariar e preservar os registros existentes e definir retorno.

Nenhuma dessas alternativas foi aplicada. Não se pressupõe que a API do
Registro.br permita a automação requerida; isso precisa ser conferido. Essa
escolha não bloqueia o trabalho de mídia e core.

Caddy já integra o proxy público da edge; emissão/renovação reais ainda aguardam
aceite. O suporte a DNS-01 depende de configuração e integração compatível com
o provedor. A delegação do
desafio também pode ser usada quando o DNS original não oferece integração.
Isso não determina uma troca do nginx privado existente; a automação DNS-01
para os nomes privados continua por definir. Ver
[HTTPS automático do Caddy](https://caddyserver.com/docs/automatic-https#dns-challenge).

## Evidências pendentes antes de publicar

| Área | O que falta comprovar |
|---|---|
| WAN e provedor de internet | Vínculo WAN e chegada externa via 10443 confirmados; localizar a falha de 80/443 entre roteador/operadora, começando por gestão remota/filtros. |
| Caminho público | 10443 é teste temporário ativo, sem TLS; o proprietário priorizou resolver 80/443 para URL sem porta. Faltam certificado e reprodução externa. |
| DNS e TLS | Emissão, renovação e retorno do certificado público testados; estratégia DNS-01 dos nomes privados ainda por definir, sem expor portas administrativas ou segredos. |
| Acesso privado | Resolução na LAN e Tailscale, rota mínima ao resolvedor e aos serviços, políticas ACL/grants efetivas e negação a clientes sem permissão. |
| Isolamento | Nenhuma rota pública aos seis nomes administrativos, aos opcionais privados ou às portas nativas; verificar também IPv6. |
| Aplicações | Origem, sessões e redirecionamentos corretos; clientes Jellyfin reproduzindo por acesso externo; administração Jellyfin negada pela entrada pública; preservação de NFS RO, lease e contenção de storage. |

O [estado de implementação](../implementation-status.md) continua sendo a
referência para o que foi executado. Este desenho não comprova publicação,
configuração do Tailscale ou recuperação automática do storage.
