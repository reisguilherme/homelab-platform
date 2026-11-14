# Estado da implementação

Data: 14/11/2026. A publicação inicial estabelece a separação de repositórios
na branch `refactor`. O servidor permanece no Ubuntu/Compose existente. A janela
de indisponibilidade depende de aviso explícito do proprietário.

| Área | Preparado neste repositório | Pendente |
|---|---|---|
| Arquitetura | Documentação geral canônica, diagramas e gaps | Aceite físico das hipóteses de isolamento e capacidade |
| Integração | Schemas, template, validador local e catálogo por commit | Conformidade dos manifests e permissões efetivas por projeto |
| Observabilidade | Compose independente com Prometheus/Grafana privados | Ativação, alvos, dashboards, consumo e ensaios no servidor |
| Proxmox/VMs | Desenho, recursos indicativos e fronteiras administrativas | Escolha autorizada do SSD, restauração ensaiada e instalação |
| Hub de arquivos | Modelo NFS e autoridade sobre mounts/exports | Consolidação verificada, exports/ACL e clientes reais |
| Energia | Estados e regras de reintegração USB | Nobreak, comunicação, coordenação host/guest e teste de falhas |
| K3s | Critérios de adoção e fronteiras | Recursos adicionais, implantação e contratos dos workloads |

O catálogo inicial registra somente integrações com arquivos publicados e
status `proposed`; não atesta serviço ativo. A integração de métricas de mídia
é a primeira unidade. O contrato do exporter não certifica o restante da stack
de mídia nem transforma Jellyfin em um processo isolado com volume somente leitura.

A preparação anterior observou o servidor por SSH e produziu um checkpoint
privado de código/configuração. A verificação de conteúdo da consolidação
anterior ainda não havia terminado. Não foi criada cópia final consistente dos
bancos. O relato e os checks dessa etapa permanecem no
[registro do projeto de mídia](https://github.com/reisguilherme/homelab-mediaserver/blob/8627cd8ff76411831c95eb0072f88998c27469e0/docs/architecture/homelab-2026/implementation-status.md).

Esta separação de repositórios não executa SSH, montagem, cópia de acervo,
formatação, reinício ou deploy. Origens de mídia e evidências privadas são
preservadas. Os [gaps](architecture/gaps.md) continuam sendo os critérios para
o corte; testes locais não substituem reprodução, GPU, rede ou recuperação física.

## Verificação da separação

- Python 3.12/WSL2, ambiente independente e `uv.lock`: `make lint` e
  `make validate` passaram. Template, catálogo e contrato `media-metrics` foram
  validados pela CLI local.
- Plataforma: 60 testes passaram e 8 foram pulados pela ausência de Docker
  Compose no WSL. A suíte de observabilidade também foi executada no Windows:
  14 passaram, incluindo normalização de Compose e override de dashboard.
  Há sobreposição entre essas rodadas; não somar como testes distintos.
- Consumidor de mídia: 113 testes pertinentes passaram e 1 check de Compose
  foi pulado no WSL. O Compose do consumidor foi conferido separadamente com
  ambiente fictício e CLI Windows, sem daemon.
- Revisão independente conferiu fronteiras, schema, links, ausência de
  credenciais administrativas e distinção entre preparação e runtime. Os
  ajustes de links e exclusão de overrides privados foram incorporados.

Esses checks não iniciaram containers nem exerceram Proxmox, disco USB, NFS,
firewall ou reprodução. A sequência de publicação fixa o schema no consumidor
e só depois registra o commit consumidor no catálogo.
