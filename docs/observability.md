# Observabilidade compartilhada da plataforma

[compose.observability.yaml](../compose.observability.yaml) pertence ao projeto
`homelab-observability`. Ele contém somente Prometheus e Grafana e não constrói,
importa ou inicia consumidores. É um Compose independente, não um override de
aplicação. Em **16/11/2026**, está implantado na homelab-control: seis targets
ativos, 22 painéis verificados no navegador e falha/resolução de coleta
ensaiadas. Consultar o [estado de implementação](implementation-status.md).

## Destino revisto: homelab-control

O proprietário reafirmou que governança e dashboards pertencem à plataforma,
independentes do projeto de mídia. Prometheus/Grafana estão implantados na
VM **homelab-control**, junto da API e portal privados, com SSD local próprio.
O desenho anterior que os colocava dentro dos 6 GiB do core foi substituído.
O [plano de governança](plans/2026-11-15-platform-governance.md) define API,
coletores e aceites; a [arquitetura de operação](architecture/operations.md)
separa ações administrativas de observação.

A VM tem 2 vCPU, 2 GiB e disco virtual de 24 GiB. A RAM veio da redução medida
do core de 6 para 4 GiB, preservando 11 GiB totais para convidados. Prometheus
mantém 512 MiB, Grafana 384 MiB e API/coletor têm teto inicial conjunto de
384 MiB; a margem interna restante atende SO/cache e processos auxiliares.
O [orçamento de storage](architecture/to-be.md#orçamento-inicial-de-recursos)
considera também transcode e o novo disco: a antiga reserva nominal de 20% do
thin pool deixou de ser verdadeira. Medir uso físico e metadata antes de criar
mais compromisso; nenhum bind ou parâmetro de retenção reserva espaço.

O portal executa ações pela API da plataforma e credenciais humanas delegadas;
Grafana continua separado dessa autoridade. O coletor de infraestrutura usa
token Proxmox exclusivo somente leitura, com ACL e TLS verificados. Ele não
recebe senha humana, ticket de sessão ou poder para iniciar/remover VMs.
Autenticação Grafana não é automaticamente a sessão Proxmox do portal: declarar
e testar cada entrada privada, sem anunciar SSO inexistente.

### Coleta, dashboards e limites

| Painel ou sinal | Fonte | Critério de aceite |
|---|---|---|
| Nó e VMs | API Proxmox, a cada 30 s | Estado, CPU, RAM, limites, projeto/pool e coleta real com timestamp |
| Storage virtual | Uso físico/capacidade da API e compromisso de discos | Diferenciar capacidade lógica, uso físico e indicador indisponível; metadata thin só quando houver fonte real |
| Operações | API e auditoria da plataforma | Intenção, tarefa em andamento, resultado e conflito; nenhum token ou body upstream |
| Saúde da coleta | Prometheus e exporter | Falha ou dado antigo aparece desconhecido, com regra de alerta e resolução |
| Storage físico e energia | Evidência sanitizada do coordenador e futuros exporters | Só exibir saúde após integração; mount presente não é prova física |
| Mídia/consumidores | Exporters privados autorizados por projeto | Catálogo ou dashboard sem target não significa aplicação monitorada |

O dashboard central deve mostrar o nó, todas as VMs autorizadas e o projeto
dono do recurso, usando `homelab` para a plataforma e `mediaserver` para mídia.
Métricas não incluem nomes de usuários, paths/títulos de mídia ou identificadores
ilimitados de operações. Auditoria detalhada é consultada na API autenticada,
não em labels públicas ou variáveis de dashboard.

Regras iniciais cobrem ausência de coleta, capacidade insuficiente e falha de
operação. Perda real de coletor e exporter por 150 s disparou os dois alertas
de fonte indisponível, que resolveram após a restauração. Entrega por
canal externo e detecção da queda total exigem integração e teste próprios;
nenhum mecanismo no mesmo host prova disponibilidade quando o host inteiro cai.
O código agora inclui o [coletor Proxmox](../services/telemetry/collector.py),
dashboard de infraestrutura e regras locais. A implantação tem coleta real
e visualização verificadas; medições sob carga continuam pendentes.

A plataforma mantém coleta, datasource e persistência centrais. Cada consumidor
mantém exporter, sanitização, snapshots, dashboard e autorização para compartilhar
métricas. O catálogo e um contrato válido não ativam coleta nem concedem acesso.
Parada, readiness e retomada de aplicações continuam sob os procedimentos próprios
e a autoridade de recuperação descritos em [operações](architecture/operations.md).

## Isolamento e preparação

Prometheus participa das redes internas `backend`, exclusiva do projeto, e
`metrics`, com nome Docker fixo `homelab-metrics`, criada por esta plataforma.
A rede `scrape` permite alcançar os exporters privados dos convidados; firewall
dos guests limita a origem à VM de controle. Grafana participa de `backend` e
da bridge normal `grafana-ui`, exclusiva desse serviço. Docker não efetiva
portas publicadas em containers ligados somente a redes `internal`, pois não
há rede com gateway padrão; a bridge adicional resolve essa dependência.
[Comportamento confirmado pelo Moby](https://github.com/moby/moby/discussions/53256).
Prometheus publica `127.0.0.1:9090:9090` para diagnóstico local;
Grafana publica `127.0.0.1:3080:3000` para o proxy privado. Não há socket Docker, devices,
privilégio global, montagem de `.env` nem acesso a bancos ou dados de consumidores.

`grafana-ui` permite tráfego de saída, sujeito ao filtro da VM de controle:
API Proxmox na porta 8006, exporters autorizados na 9100 e HTTP/HTTPS público,
DNS e NTP conforme os destinos permitidos pela plataforma. Não há garantia de
saída zero para Grafana. Relatórios de analytics, consultas de atualização do
Grafana/plugins e pré-instalação de plugins ficam desativados na configuração;
esses controles de aplicação não substituem o filtro de rede. O vínculo
`127.0.0.1:3080` restringe a entrada publicada ao host da VM, não a saída do
container. Conferir o bind efetivo, acesso pelo proxy TLS e recusa pela LAN
após recriar o container; somente `docker compose config` não prova publicação.

A rede de métricas compartilhada pressupõe projetos no **mesmo daemon Docker**; o nome
não cria uma rede entre VMs, hosts ou K3s. Exporters aderem como rede `external` e
recebem somente os mounts dedicados necessários. Um participante dessa rede pode
alcançar outros participantes: `internal: true` não implementa ACL por consumidor.
Separação por VM e eventual telemetria entre hosts exigem desenho privado próprio;
não abrir portas públicas para contornar essa limitação.

Antes de qualquer ativação manual, confirmar Linux, Docker Compose, capacidade em
SSD local e destino dos diretórios. Não usar NFS, mergerfs, USB ou pasta de mídia
para o TSDB e banco Grafana. Preparar somente os diretórios do projeto, sem
formatar, montar ou alterar `fstab`. Todos os binds têm `create_host_path: false`.

Copiar [.env.example](../.env.example) para `.env` privado e substituir as
credenciais fictícias por valores exclusivos. O Compose de observabilidade usa:

| Variável | Uso |
|---|---|
| `HOMELAB_GRAFANA_ADMIN_USER` / `HOMELAB_GRAFANA_ADMIN_PASSWORD` | Credenciais obrigatórias do administrador inicial |
| `HOMELAB_OBSERVABILITY_DIR` | Persistência central; default `/srv/appdata/homelab-observability` |
| `HOMELAB_PROMETHEUS_TARGETS_DIR` | Diretório privado preexistente obrigatório para file discovery |
| `HOMELAB_GRAFANA_ROOT_URL` | URL externa HTTPS com o subpath `/grafana/` |

A API e o coletor têm configuração adicional, descrita na
[preparação do controle](../infrastructure/control/README.md) e na tabela abaixo.

Não há `*_FILE`. Só as duas credenciais selecionadas chegam ao Grafana; o `.env`
inteiro não é repassado. Não imprimir Compose interpolado com credenciais reais.
As variáveis de administrador inicial não rotacionam uma conta de banco existente.

Instruções para os caminhos padrão, após confirmar o SSD de destino:

```bash
sudo install -d -m 0755 /srv/appdata/homelab-observability
sudo install -d -o 65534 -g 65534 -m 0750 /srv/appdata/homelab-observability/prometheus
sudo install -d -o 472 -g 472 -m 0750 /srv/appdata/homelab-observability/grafana
sudo install -d -o 65534 -g 65534 -m 0750 /srv/appdata/homelab-observability/targets
```

Ajustar todos os caminhos se personalizados no `.env`. UID/GID 65534 lê configuração
e grava TSDB; UID/GID 472 grava dados Grafana. Provisioning versionado deve ser
legível por esses usuários. Não usar diretório de controle, inventário ou segredos
como targets. O arquivo privado de targets precisa ser legível pelo UID 65534,
por exemplo dono/grupo 65534 e modo 0640, sem expor seu conteúdo a outros usuários.

## Targets por adesão explícita

O diretório privado pode começar vazio. Nesse caso não há consumidores ou
exporters de guests cadastrados. Os jobs fixos coletam Prometheus e o exporter
`homelab-pve-metrics:9101`; antes de iniciar o Compose de controle, este último
fica indisponível e o alerta local corresponde a essa ausência. Não interpretar
self-scrape como monitoramento de aplicações. Consumidores usam `file_sd_configs`
em `/etc/prometheus/targets/*.json`, com refresh de 30 s e mount somente leitura.

Guests têm job próprio em `/etc/prometheus/targets/guests/*.json`, a cada 30 s,
timeout de 5 s, teto de 5.000 amostras e corpo de 5 MiB. Criar o subdiretório
privado e adaptar [guests.example.json](../deploy/observability/targets/guests.example.json),
que contém apenas endereços de documentação. Não colocar o arquivo de guests na
raiz: isso o incluiria no job de consumidores com orçamento diferente. Cada
target recebe labels `guest`, `project` e `role` estáveis. O pacote
`prometheus-node-exporter` roda dentro de cada guest, bind no IP privado e porta
9100 com acesso apenas da VM de controle; não instalar uma nova unit no Proxmox.

O dashboard inclui CPU/RAM internos, espaço dos mounts `/srv/external3` e
`/srv/transcode`, readonly observado, latência de disco e métricas NFS quando
presentes. Nenhum desses sinais substitui o lease/coordenador ou comprova
integridade física. Lease, SMART, energia e temperatura sem exporter real
continuam desconhecidos. O collector NFS usa sinais de `/proc`; ausência em
guest sem cliente NFS é esperada. [Fonte do node_exporter](https://github.com/prometheus/node_exporter/blob/master/collector/nfs_linux.go).

[targets/media.example.json](../deploy/observability/targets/media.example.json)
é apenas um exemplo versionado fora do mount. Após preparar a rede e o exporter
do consumidor, o operador pode copiar o exemplo para um arquivo regular `.json`
no diretório privado e ajustar dono/permissões. Não apontar o diretório privado
para a pasta de exemplos: adesão exige decisão e arquivo próprios. Para começar
sem consumidores, usar diretório vazio ou arquivo com `[]`.

O exemplo aponta a `media-metrics:8090` e inclui `job: homeserver`, compatível com
o dashboard mantido por mídia. Esse alias depende de adesão do exporter à mesma
rede `homelab-metrics`; não é hostname público. O operador deve evitar colisões de
aliases ao integrar outros projetos. Cada target é autorizado explicitamente;
não inventariar containers ou importar targets automaticamente do catálogo.
Atualizar arquivos privados por substituição atômica; retirar o arquivo interrompe
coleta futura, mas não elimina séries históricas já persistidas.

Scrapes ocorrem a cada 15 s, timeout de 5 s. O job `consumers` limita cada scrape
a 128 amostras e corpo de 1 MiB e usa `honor_labels: false`. Avaliar esse orçamento
antes de admitir outros exporters. Não há `remote_write` ou Alertmanager.
As regras de `deploy/observability/rules/platform.yml` são avaliadas localmente
pelo Prometheus e aparecem no dashboard; não enviam notificações externas.

## Dashboard opcional do consumidor

A base provisiona o datasource `Homelab Prometheus`, UID `homelab-prometheus`, com
proxy privado `http://prometheus:9090`. A pasta versionada contém
`infrastructure.json`, com métricas de nó/VM/storage/guests/tarefas/coleta e
alertas locais. O checkout funciona sem caminho externo ou repo de mídia.

Mídia mantém `deploy/metrics/dashboards/homeserver.json` no próprio repositório.
Para optar por esse painel, o operador obtém o arquivo de um commit revisado e o
coloca em diretório privado dedicado de dashboards. Pode então criar **fora do
Git** um override `compose.dashboards.yaml` na raiz da plataforma, por exemplo:

```yaml
services:
  grafana:
    volumes:
      - type: bind
        source: ${HOMELAB_GRAFANA_DASHBOARDS_DIR:?Set a private existing dashboard directory}
        target: /var/lib/grafana/dashboards
        read_only: true
        bind:
          create_host_path: false
```

Esse override substitui toda a pasta de dashboards: copiar também o painel
versionado de infraestrutura para o diretório privado se quiser preservá-lo.
Definir `HOMELAB_GRAFANA_DASHBOARDS_DIR` no `.env` privado somente ao usar esse
override. Arquivos devem ser legíveis pelo UID 472. O merge substitui o mount do
mesmo target; não monta checkout completo, dados ou segredos de consumidores.
Validar com o mesmo projeto e ambos os arquivos antes da ativação manual:

```bash
docker compose -p homelab-observability --env-file .env -f compose.observability.yaml -f compose.dashboards.yaml config --quiet
```

Nas operações seguintes, acrescentar esse mesmo `-f compose.dashboards.yaml`
quando adotado. O provisionamento desabilita alterações pela UI; alterações
versionáveis do dashboard pertencem ao consumidor. Ausência de dados não significa
valor zero, disco saudável ou readiness para retomar downloads.

## Operação manual e orçamento

O [Compose de controle](../compose.control.yaml) inicia API e coletor separados.
Construir sua imagem com `docker compose -p homelab-control --env-file .env -f
compose.control.yaml build` antes de iniciar esses serviços. O Dockerfile usa
allowlist de contexto: checkout privado, `.env`, bancos e `.artifacts` não entram
na imagem. A API usa UID/GID 10001 e diretório SSD preexistente
`HOMELAB_CONTROL_DIR` (default `/srv/appdata/homelab-control`), com acesso de
escrita apenas a esse estado. O coletor não recebe mounts persistentes.

| Variável adicional | Uso |
|---|---|
| `PVE_URL` | Origem HTTPS fixa do Proxmox, com nome/IP coberto pelo certificado |
| `PVE_CA_PEM` | Certificado CA público literal, usado para verificar TLS e hostname |
| `PVE_METRICS_TOKEN_ID` / `PVE_METRICS_TOKEN_SECRET` | Token RO de coleta, também mapeado a `PVE_CAPACITY_TOKEN_ID`/`PVE_CAPACITY_TOKEN_SECRET` no backend para prova de capacidade; nunca autoriza ação humana |
| `PVE_CAPACITY_ROLE` | Papel RO esperado na prova de capacidade; Compose fixa `HomelabMetrics` |
| `PLATFORM_ORIGIN` | Origem HTTPS exata do portal; sessão e CSRF dependem dela |
| `PVE_WEB_URL` / `GRAFANA_URL` | Links HTTPS privados sem tickets em URL |
| `CONTROL_PROFILES_JSON` | Perfis de criação revisados no servidor |
| `CONTROL_PROTECTED_VMIDS` / `CONTROL_ALLOWED_NODES` | Proteção de alvos e nós permitidos na API |
| `CONTROL_VM_ID` / `CONTROL_DEPENDENCIES_JSON` | Identidade protegida do controle e dependências sanitizadas por VM, definidas no servidor |
| `HOMELAB_GRAFANA_ROOT_URL` | Origem externa e subpath `/grafana/` |

Criar usuário/token de coleta com privilégio separado, expiração e ACL RO para
inventário e tarefas dos nós necessários. Conferir permissões efetivas do
usuário **e** token; um login válido com inventário parcial não comprova cobertura.
A prova de capacidade do backend exige os três privilégios RO globais
`Sys.Audit`, `VM.Audit` e `Datastore.Audit`, ACLs propagadas de usuário/token
sem overrides ou grupos e `privsep=1`; verifica a autoridade antes e depois
do snapshot. Esse adapter só executa GET. Mutações usam a sessão humana
delegada; o endpoint ACL não permite modificar o principal interno de coleta.
O coletor só chama GET `/cluster/resources` e GET `/nodes/{node}/tasks`, sem
seguir redirects ou proxies do ambiente. Respostas têm limite de 1 MiB,
requisições timeout de 5 s e janela de coleta limitada. Não imprimir o Compose
interpolado com `.env` real. O PEM público não é segredo, mas o token é.

As tarefas são contadas em até 100 resultados da última hora; a métrica
`homelab_pve_tasks_window_limited` indica truncamento. Não é um contador histórico
de todas as operações. Erros e nomes de usuário/tarefa não viram labels.
`/healthz` prova somente processo HTTP; `homelab_pve_collection_up`, sinais por
fonte e timestamp indicam coleta completa/parcial. Falha remove amostras da
fonte; após 75 s sem ciclo, nenhum dado antigo de recurso continua exposto como
atual. O último timestamp completo permanece para alertar atraso.

Executar na raiz deste repo somente após as pré-condições. Sempre manter
`-p homelab-observability`: `COMPOSE_PROJECT_NAME` do ambiente pode sobrepor o
`name` do YAML. A plataforma deve criar sua rede antes de iniciar exporters; uma
rede ausente causa falha de adesão do consumidor, sem iniciar a aplicação.

```bash
docker compose -p homelab-observability --env-file .env -f compose.observability.yaml config --quiet
docker compose -p homelab-observability --env-file .env -f compose.observability.yaml up -d
docker compose -p homelab-observability --env-file .env -f compose.observability.yaml ps
docker compose -p homelab-observability --env-file .env -f compose.observability.yaml logs --tail=100
docker compose -p homelab-observability --env-file .env -f compose.observability.yaml restart grafana
```

Depois da rede `homelab-metrics` existir, iniciar a imagem construída com
`docker compose -p homelab-control --env-file .env -f compose.control.yaml up -d`.
A API publica apenas loopback 8080; o coletor 9101 fica sem porta publicada.
O proxy privado faz HTTPS e encaminha o portal e `/grafana/`. Grafana exige
cookie Secure e a própria sessão; acessar diretamente HTTP3080 não é o fluxo
de login suportado. Rede/targets/containers saudáveis não dispensam os testes
de série real, falha de fonte e isolamento entre VMs.

Grafana atende por subpath `/grafana/`, com URL externa privada definida em
`HOMELAB_GRAFANA_ROOT_URL` (default `https://127.0.0.1:18443/grafana/`). O proxy
HTTPS e o túnel privado precisam estar efetivamente configurados e testados;
bind loopback e sucesso de `config` não comprovam acesso remoto. A sessão
Grafana continua própria. Não publicar 3080/9090 ou exporters no roteador.

| Componente | Teto RAM | Persistência |
|---|---:|---|
| Prometheus | 512 MiB | SSD local; retenção 7 dias ou 4 GiB |
| Grafana | 384 MiB | SSD local; banco/configuração/plugins |
| Observabilidade base | 896 MiB | API/coletor e SO têm orçamento adicional dentro da VM de controle |

São tetos experimentais, não medições ou reserva física. Reservar inicialmente
8 GiB de SSD para Prometheus, pelo menos 1 GiB separado para Grafana e margem
para logs, WAL/head, compactação e crescimento. `4GB` usa potência de dois;
a primeira política atingida encerra retenção. Limpeza assíncrona e WAL podem
exceder 4 GiB. Binds não criam quota. Logs giram em dois arquivos de 10 MiB por
container. Monitorar espaço, RAM/OOM e latência durante o ensaio. Não há Loki,
Alloy, traces ou coleta geral de containers.

As imagens implantadas preservam as versões fixadas:
`prom/prometheus:v3.13.5` e `grafana/grafana:13.3.1`. A coleta e o provisionamento
foram verificados em runtime; atualizações futuras exigem revisão e novo ensaio.

Para desligar, primeiro parar os exporters dos consumidores e depois usar:

```bash
docker compose -p homelab-observability --env-file .env -f compose.observability.yaml down
```

Exporters ainda conectados podem impedir remoção da rede; não forçar remoção nem
afetar o projeto de mídia para contornar isso. Os binds persistem. Não apagar
TSDB ou banco Grafana para corrigir inicialização. Conferir logs, permissões e
configuração, mantendo uma autoridade para incidentes de storage. Histórico local
não protege contra falha do mesmo SSD/host; a queda pode derrubar o próprio painel.

## Evidência e lacunas

Os testes verificam estrutura, isolamento, targets opt-in e Compose com ambiente
fictício explícito e `DOCKER_CONFIG` temporário, sem daemon ou `.env` real:

```bash
uv sync --frozen
uv run --frozen pytest tests/test_telemetry_collector.py tests/test_observability.py -q
```

No destino, a implantação de 16/11 confirmou os seis targets: quatro exporters
de guests, coletor PVE e self-scrape. O dashboard tem 22 painéis provisionados.
No navegador real, as 22 consultas retornaram HTTP 200 sem erro: 21 tinham
séries/linhas, enquanto a consulta de alertas firing vazia exibiu “Sem dados”.
Login/logout próprios do Grafana e layouts desktop/390 px passaram sem
overflow ou exceções; ausência de série não foi convertida em saúde.
O ensaio real interrompeu coletor e exporter do controle por 150 s:
`GuestExporterUnavailable` e `ProxmoxCollectionUnavailable` dispararam e
resolveram após a volta das fontes. Ao final, todos os targets estavam ativos
e não havia alertas. Isso não comprova entrega por canal externo.

O reboot do controle preservou banco Grafana, histórico SQLite e seis targets,
com quatro containers em execução sem OOM. O autostart usa ordem 5 antes da
mídia. A suíte local final passou em 236 testes pytest, Ruff check/format e dez
testes Node. Permanecem pendentes medição sob carga, notificações
externas e sonda independente do host. A auditoria SQLite não tem poda
automática; a retenção Prometheus não se aplica a ela. Em mudanças futuras,
revalidar config/regras com `promtool`, dados reais e ausência de fonte.
Consulte [lacunas](architecture/gaps.md).
