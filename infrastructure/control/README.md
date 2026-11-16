# VM de governança

`homelab-control` pertence à plataforma, com tags `homelab`, `governance` e
`observability`. O perfil inicial usa 2 vCPU, 2 GiB de RAM e disco virtual novo
de 24 GiB no SSD. O core de mídia foi realocado de 6 para 4 GiB após medição e
parada coordenada, mantendo 11 GiB no orçamento dos convidados. O acervo não
fica no disco da governança.

O provisionamento importa a cloud image Ubuntu previamente verificada, fixa
um `instance-id` próprio e instala QGA, Docker, Nginx e node_exporter no guest.
A firewall permite SSH e HTTPS somente pelo host de gestão; a saída para a
API Proxmox e para os exporters dos convidados tem destinos e portas fixos.
Regras de anti-spoofing também devem cobrir a nova interface. Não reaplicar o
bootstrap inicial das três VMs sobre a rede ou IDs existentes.

O [proxy](nginx.conf) usa a unit Nginx do convidado e termina TLS em 8443. API,
Prometheus e Grafana escutam somente em loopback. O acesso inicial usa túnel
SSH de gestão; `PLATFORM_ORIGIN` deve coincidir exatamente com a origem HTTPS
aberta no navegador. Grafana usa `/grafana/` nessa origem. A chave TLS é gerada
e permanece no guest; a CA e o certificado públicos podem ser distribuídos.
Não desabilitar verificação de certificado para acessar a API Proxmox.

Antes de iniciar os dois projetos Compose, criar no SSD os diretórios de
estado com proprietários correspondentes: API 10001, Prometheus 65534 e
Grafana 472. A `.env` privada fornece tokens, senha Grafana, CA pública PEM e
perfis permitidos. O token de coleta recebe somente auditoria, separado das
sessões humanas. A API nunca recebe chave SSH root ou socket Docker.

## Configuração e inicialização

O [.env.example](../../.env.example) contém valores fictícios e uma lista de
VMIDs vazia, que bloqueia criação até revisão. Copiar para `.env` privado e
substituir destinos, CA, credenciais e inventário antes de iniciar.

| Variável | Responsabilidade |
|---|---|
| `PLATFORM_ORIGIN` | Origem HTTPS exata aberta pelo navegador; usada contra CSRF |
| `PVE_URL`, `PVE_CA_PEM` | API fixa e CA pública confiável; certificado deve cobrir hostname/IP |
| `PVE_WEB_URL`, `GRAFANA_URL` | Links HTTPS dos consoles; nenhum token na URL |
| `PVE_METRICS_TOKEN_ID`, `PVE_METRICS_TOKEN_SECRET` | Identidade RO separada para métricas e prova de capacidade |
| `CONTROL_ALLOWED_NODES`, `CONTROL_PROFILES_JSON` | Nós e perfis de hardware permitidos, IDs e reservas |
| `CONTROL_VM_ID`, `CONTROL_PROTECTED_VMIDS`, `CONTROL_DEPENDENCIES_JSON` | Identidade do controle, exclusões protegidas e dependências conhecidas |
| `HOMELAB_CONTROL_DIR` | SQLite no SSD local, com proprietário 10001 |

Para o token de capacidade, o papel `HomelabMetrics` deve conter exatamente
`Sys.Audit VM.Audit Datastore.Audit`. Usuário e token com `privsep=1` recebem
ACL propagada em `/`; essa identidade não participa de grupos nem recebe
outras ACLs. A API verifica essa configuração antes de confiar no inventário
para capacidade. Isso não concede poder administrativo ao token.

O acesso humano é delegado ao Proxmox. Criar o hardware do perfil exige
`VM.Allocate`, `VM.Audit`, `VM.Config.CPU`, `VM.Config.Memory`,
`VM.Config.Options` e `VM.Config.HWType` no ID permitido, além de
`Datastore.AllocateSpace` no storage. Conceder somente os papéis e caminhos
necessários; a API não substitui a validação de permissões do Proxmox.

Com diretórios, targets e TLS preparados, executar da raiz deste repositório:

```bash
docker compose -f compose.observability.yaml config --quiet
docker compose -f compose.control.yaml config --quiet
docker compose -f compose.observability.yaml up -d
docker compose -f compose.control.yaml up -d --build
```

O primeiro projeto cria a rede `homelab-metrics` exigida pelo coletor. Não
imprimir `docker compose config` interpolado com o ambiente real. A API usa
um único worker, com sessões em memória; reinício encerra sessões, enquanto
intenções e auditoria permanecem no SQLite. Grafana mantém login independente.
O log de acesso do proxy omite query strings e headers.

## Escopo das operações

O perfil de criação inicial entrega hardware desligado, sem sistema instalado
e sem NIC. A interface deve informar essa condição. Limites de CPU, memória,
disco, VMIDs, projetos e reservas pertencem ao operador. Não abrir criação
irrestrita para contornar falta de capacidade. As operações com dependências
de storage e hardware avançado mantêm procedimentos próprios e o console
Proxmox como caminho independente.

Consulte o [plano](../../docs/plans/2026-11-15-platform-governance.md) e o
[estado de implementação](../../docs/implementation-status.md) para distinguir
código, provisionamento e aceites reais da API, dos painéis e do isolamento.
