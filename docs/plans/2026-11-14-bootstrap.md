# Implementação inicial de homelab-platform

Spec: [separação aprovada](../design/repository-separation.md).

## Restrições e aceite

Somente repositórios; nenhuma operação SSH/deploy/disco. Nenhum segredo, dado ou
inventário privado. Preservar o histórico e os contratos da aplicação. A publicação
foi autorizada, sem necessidade de reconfirmar. Repositório principal refactor
limpo; novo checkout independente em diretório ignorado do workspace.

Aceite: docs gerais canônicas, contratos e catálogo validáveis, observabilidade
separada do build de mídia, ligação explícita do consumidor, checks locais/revisão,
commits publicados nos destinos corretos. Runtime permanece pendente.

## Task A — Arquitetura e operação

Owner: agente docs. Criar docs/architecture/{README,as-is,to-be,operations,
power-recovery,security,gaps}.md e docs/repositories.md. Adaptar a documentação
existente sem perder requisitos, limites e evidências; referências ao código de
mídia usam commit8627cd8ff76411831c95eb0072f88998c27469e0 no GitHub. Não copiar
inventário privado nem HTML com links/diagramas desatualizados. Usar Mermaid no
Markdown; corrigir links locais. Distinguir runtime as-is da nova posse dos repos.
Não criar deploy de Proxmox/K3s: documentar precondições e gaps com clareza.

## Task B — Contrato, catálogo e validação

Owner: agente contracts. Criar contracts/v1/service.schema.json,
contracts/v1/catalog.schema.json, templates/service.contract.json,
catalog/services.json inicial vazio, scripts/validate.py, tests/test_contracts.py,
pyproject.toml, uv.lock, Makefile, docs/integration-contract.md.

Interface CLI: `python scripts/validate.py service PATH` ou `catalog PATH`, exit0
se válido, exit1 se inválido; erros sem valores sensíveis. JSON Schema Draft202012,
Python3.12 e jsonschema com dependências fixadas no lock. Sem I/O de rede na
validação, sem escrita/deploy. Unknown fields recusados; limitar enums, números e
paths. Schema escolhido deve contemplar apiVersion, id/repositório, runtime
compose-vm ou k3s, recursos solicitados, rede/gestão privada, storage RO/RW/tipo,
telemetria/saúde, nomes de segredos e regras de recuperação. Validar DB em storage
apropriado e rejeitar herança de privilégio administrativo global. Declarar
compatibilidade não concede autorização/capacidade; catálogo separa proposed de
deployed e exige commit40hex/pathrelativo para consumidor registrado.

Testes RED/GREEN: exemplo válido; campos inesperados/secret values; versão errada;
recursos negativos; DB em compartilhamento inadequado; admin público; path traversal;
catálogo sem commit imutável; duplicação de IDs. Documentar o schema exato entregue
e limites de validação sem prometer ACL ou readiness reais.

## Task C — Separação da observabilidade

Owner: agente observability. Novo repo: compose.observability.yaml, .env.example,
deploy/observability/**, docs/observability.md, tests/test_observability.py. Atual
repo mídia: compose.observability.yaml vira somente exporter; remover provisioning
central deploy/observability (preservar dashboard específico em deploy/metrics/),
adaptar docs/observability.md e tests/contract/test_observability_compose.py.

Plataforma somente Prometheus+Grafana, imagens já verificadas/pinadas3.13.5/13.3.1,
mesmos limites512/384MiB e retenção7d/4GiB. Sem build/import do repo de mídia.
Grafana loopback; Prometheus sem hostport. Rede backend interna e rede de métricas
interna compartilhável com nome fixo homelab-metrics, criada pela plataforma.
Exporter do consumidor entra como rede external, alias media-metrics; só lê os
snapshots dedicados, sem porta de host. Prometheus usa file_sd em diretório privado
preexistente, exemplo de target media-metrics:8090 opt-in. Config inicial pode ter
lista vazia e self-scrape; deixar explícito que isso não monitora aplicações.

Credenciais da plataforma usam HOMELAB_GRAFANA_ADMIN_USER/PASSWORD, basepath
HOMELAB_OBSERVABILITY_DIR, targets HOMELAB_PROMETHEUS_TARGETS_DIR. Não mudar o
publicador nem os campos HOMESERVER_ aceitos por compatibilidade na aplicação.
Comandos sempre -p explícito; preparar diretórios/UIDs/grupos somente em instruções.
Dashboard de mídia e exporter são mantidos pelo consumidor e montados de forma
opt-in pelo operador da plataforma, sem caminho absoluto local obrigatório.

Testar estrutura/isolation/targets e merge com env fictício. Nunca acessar daemon,
executar up/down ou imprimir Compose interpolado com segredo real. Preservar
limites/lacunas de runtime no guia e independência do coletor atual sem opt-in.

## Task D — Integração e publicação

Owner: root. README, índice de implementação, links, contrato do consumidor e lock
do contrato da plataforma. Docs gerais antigas na mídia viram ponte para fonte
canônica, com histórico preservado em Git; documentos de execução de mídia ficam.
Não alterar Compose principal nem implementação da aplicação.

Publicar plataforma inicial C1 (catálogo vazio, contrato e docs), fixar C1 em
platform.lock.json da mídia e adicionar platform.contract.json validado; publicar
mídia C2 em refactor. Atualizar catálogo plataforma para C2, com status proposed,
e publicar C3. Evitar ciclo impossível de commits que se referenciam mutuamente.
Revisão independente, lint/testes pertinentes, links, exclusão de dados privados,
readback dos refs remotos. Sem merge no main e sem implantação.

## Foco de revisão

- Docs e schemas compatíveis; documentação não concede permissão.
- Nenhuma dependência de build/media/env no repo plataforma.
- Rede externa somente no consumidor; nomes/projeto/targets sem colisão.
- Catálogo aponta a commit que realmente contém os arquivos declarados.
- Separação não remove guards/recuperação nem inicia serviços implicitamente.
