# Observabilidade compartilhada opcional

[compose.observability.yaml](../compose.observability.yaml) pertence ao projeto
`homelab-observability`. Ele contém somente Prometheus e Grafana e não constrói,
importa ou inicia consumidores. É um Compose independente, não um override de
aplicação. A configuração entregue não foi aplicada ao servidor.

A plataforma mantém coleta, datasource e persistência centrais. Cada consumidor
mantém exporter, sanitização, snapshots, dashboard e autorização para compartilhar
métricas. O catálogo e um contrato válido não ativam coleta nem concedem acesso.
Parada, readiness e retomada de aplicações continuam sob os procedimentos próprios
e a autoridade de recuperação descritos em [operações](architecture/operations.md).

## Isolamento e preparação

Prometheus participa de duas redes internas: `backend`, exclusiva do projeto, e
`metrics`, com nome Docker fixo `homelab-metrics`, criada por esta plataforma.
Grafana participa somente de `backend`. Prometheus não publica porta no host;
Grafana publica apenas `127.0.0.1:3000:3000`. Não há socket Docker, devices,
privilégio global, montagem de `.env` nem acesso a bancos ou dados de consumidores.

Essa rede compartilhada pressupõe os projetos no **mesmo daemon Docker**; o nome
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
credenciais fictícias por valores exclusivos. A plataforma usa apenas:

| Variável | Uso |
|---|---|
| `HOMELAB_GRAFANA_ADMIN_USER` / `HOMELAB_GRAFANA_ADMIN_PASSWORD` | Credenciais obrigatórias do administrador inicial |
| `HOMELAB_OBSERVABILITY_DIR` | Persistência central; default `/srv/appdata/homelab-observability` |
| `HOMELAB_PROMETHEUS_TARGETS_DIR` | Diretório privado preexistente obrigatório para file discovery |

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

O diretório privado pode começar vazio. Nesse caso Prometheus coleta somente a si
mesmo; isso **não monitora aplicações**, snapshots, storage do servidor ou saúde de
VMs. A configuração usa `file_sd_configs` em `/etc/prometheus/targets/*.json`, com
refresh de 30 s; o diretório é montado somente para leitura.

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
antes de admitir outros exporters. Não há `remote_write`, Alertmanager ou alertas.

## Dashboard opcional do consumidor

A base provisiona o datasource `Homelab Prometheus`, UID `homelab-prometheus`, com
proxy privado `http://prometheus:9090`. A pasta versionada de dashboards começa
vazia. O checkout da plataforma funciona sem caminho externo ou repo de mídia.

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

Abrir `http://127.0.0.1:3000` no host apropriado. Acesso remoto depende de caminho
privado autenticado configurado separadamente; este repo não cria Tailscale,
proxy, MFA ou publicação no roteador. Não usar sucesso de `config` como prova de
acesso remoto ou isolamento físico.

| Componente | Teto RAM | Persistência |
|---|---:|---|
| Prometheus | 512 MiB | SSD local; retenção 7 dias ou 4 GiB |
| Grafana | 384 MiB | SSD local; banco/configuração/plugins |
| Plataforma total | 896 MiB | Exporters são orçamento adicional dos consumidores |

São tetos experimentais, não medições ou reserva física. Reservar inicialmente
8 GiB de SSD para Prometheus, pelo menos 1 GiB separado para Grafana e margem
para logs, WAL/head, compactação e crescimento. `4GB` usa potência de dois;
a primeira política atingida encerra retenção. Limpeza assíncrona e WAL podem
exceder 4 GiB. Binds não criam quota. Logs giram em dois arquivos de 10 MiB por
container. Monitorar espaço, RAM/OOM e latência durante o ensaio. Não há Loki,
Alloy, traces ou coleta geral de containers.

As imagens preservam as versões fixadas e verificadas na preparação de 14/11/2026:
`prom/prometheus:v3.13.5` e `grafana/grafana:13.3.1`. Não foi feito pull ou teste
dessas imagens nesta separação. Verificar atualizações antes do ensaio.

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
uv run --frozen pytest tests/test_observability.py -q
```

Isso não prova provisioning em runtime, permissões do SSD, renderização, acesso
remoto, consumo de RAM, entrega de alertas ou recuperação física. Alertas exigem
regras, canal, duração, severidade, responsável, resolução e teste de entrega;
continuam pendentes. Consulte [lacunas](architecture/gaps.md).
