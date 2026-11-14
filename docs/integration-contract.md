# Contrato de integração v1

O contrato declara o pedido de uma unidade implantável de um consumidor. Uma
unidade pode agrupar containers com o mesmo escopo; componentes com permissões
diferentes devem ser descritos por unidades distintas. O catálogo registra a
proposta ou o estado declarado pelo operador. Nenhum dos dois concede acesso,
reserva capacidade, implanta serviços ou comprova readiness.

Os schemas [service](../contracts/v1/service.schema.json) e
[catalog](../contracts/v1/catalog.schema.json) usam JSON Schema Draft 2020-12.
Todos os objetos recusam campos desconhecidos. Todos os campos abaixo são
obrigatórios, exceto as duas portas opcionais de telemetria. Arrays vazios são
permitidos quando não há pedidos correspondentes; `manifestPaths` exige ao
menos um item. O [template](../templates/service.contract.json) usa valores
fictícios e precisa ser adaptado, sem copiar credenciais.

## Declaração de serviço

| Campo | Formato e significado |
| --- | --- |
| `apiVersion` | Exatamente `homelab/v1`. |
| `id` | Até 63 caracteres: letra minúscula inicial, letras/números e segmentos separados por hífen. Identifica a unidade, não precisa ser o nome do repositório. |
| `repository` | URL HTTPS `https://github.com/OWNER/REPO`, sem credenciais, query, fragmento ou barra final. |
| `runtime` | `compose-vm` ou `k3s`; declarar K3s não significa que ele já exista. |
| `resources.cpu` | Número maior que zero, até 128; frações representam CPU solicitada. |
| `resources.memoryMiB` | Inteiro entre 16 e 1048576 MiB. |
| `resources.gpu` | `none`, `intel-qsv` ou `nvidia`; solicitação declarativa, sem ativar GPU ou autorizar RTX. |
| `network.administration` | Exatamente `private`. |
| `network.inheritPlatformPrivileges` | Exatamente `false`. Autenticação no painel do consumidor não herda administração global da plataforma. |
| `network.exposure` | `private` ou `public`, descrevendo a aplicação. Administração e métricas continuam privadas. |
| `network.ingress` | Lista de `{port, protocol, scope, purpose}`. Porta inteira 1–65535; protocolo `tcp` ou `udp`; escopo `private` ou `public`; finalidade `application`, `administration` ou `metrics`. As duas últimas exigem escopo privado. São portas lógicas solicitadas, sem criar publicação no host. |
| `network.egress` | Lista de `{dependency, port, protocol}`. `dependency` é um nome lógico com a mesma sintaxe de `id`; porta e protocolo seguem ingress. Não contém endereços privados nem credenciais. A resolução e a política efetiva dependem do operador. |
| `storage` | Até 64 pedidos conforme a tabela seguinte, com IDs únicos por serviço. |
| `telemetry.metricsPath` | Path HTTP absoluto, como `/metrics`, ou `null` quando não há métricas. |
| `telemetry.healthcheckPath` | Path HTTP absoluto, como `/health/live`. Declara o endpoint de saúde, sem afirmar que readiness ou recuperação já foram testadas. |
| `telemetry.metricsPort` | Opcional, inteiro 1–65535. Só pode aparecer quando `metricsPath` contém um path. |
| `telemetry.healthcheckPort` | Opcional, inteiro 1–65535. Correspondente ao path de saúde. |
| `secrets` | Até 128 nomes únicos de variáveis de ambiente: letra maiúscula inicial, letras maiúsculas/números/underscore, até 128 caracteres, sem sufixo `_FILE`. Somente referências; valores ficam no `.env` privado da implantação. |
| `recovery.authority` | `consumer` ou `platform`; identifica quem coordena a recuperação desta unidade. O runbook deve deixar explícita a interação com o responsável pelo incidente físico. |
| `recovery.runbookPath` | Path relativo ao repositório consumidor no commit registrado. |
| `recovery.requiresStorageReady` | Exatamente `true`. Retomada exige validação prévia de storage e dependências. |
| `recovery.preserveOperatorPauses` | Exatamente `true`. Recuperação preserva pausas explícitas do operador. |

| Campo de cada pedido de storage | Formato e significado |
| --- | --- |
| `id` | Nome lógico único com a sintaxe de `id`. |
| `mountPath` | Path POSIX absoluto dentro da unidade, até 256 caracteres, sem raiz isolada, segmentos `.`/`..`, barras repetidas ou barra final. Não declara dispositivo físico nem path privado do host. |
| `kind` | `local-block`, `network-share` ou `mergerfs`. |
| `access` | `ro` ou `rw`. |
| `purpose` | `database`, `media`, `config` ou `cache`. |
| `requestedGiB` | Número maior que zero, até 1048576 GiB. Orçamento solicitado, sem reservar espaço nem comprovar capacidade. |

Pedidos de `database` exigem `local-block` e `rw`. Isso inclui bancos embutidos;
se uma aplicação mistura configuração e SQLite no mesmo volume, esse volume
deve declarar finalidade `database`. O schema não inspeciona o conteúdo do volume
nem identifica bancos escondidos sob outra finalidade. Shares e mergerfs não
são aceitos para bancos nesta versão.

Paths HTTP têm um ou mais segmentos de letras ASCII, números, `_` e `-`, sem
query, fragmento, credenciais, encoding percentual ou traversal. Paths de
arquivos relativos têm até 256 caracteres, segmentos de letras ASCII, números,
`_`, `-` e `.`, sem segmentos `.`/`..`, barras repetidas, barra final, drive Windows
ou barra invertida. Paths não são resolvidos, abertos nem seguidos como symlinks.

Os máximos são limites sintáticos, não o inventário ou a capacidade deste host.
O operador deve revisar recursos, permissões RO/RW, rede e egress antes de aplicar
qualquer manifesto. Endpoints de métricas só entram no coletor por opt-in.

## Catálogo

[catalog/services.json](../catalog/services.json) registra primeiro a unidade
`media-metrics` como `proposed`, após a publicação do commit consumidor. Um
catálogo vazio (`services: []`) também é válido. O objeto raiz exige
`apiVersion: "homelab/v1"` e `services`, com até 256 entradas.
Cada entrada exige:

| Campo | Regra |
| --- | --- |
| `id` | Mesmo ID da unidade no contrato, único no catálogo. |
| `repository` | Mesma sintaxe HTTPS GitHub do serviço. |
| `commit` | Exatamente 40 caracteres hexadecimais minúsculos; branches e tags são recusados. |
| `contractPath` | Path relativo do contrato no commit consumidor. |
| `manifestPaths` | Lista de 1–32 paths relativos únicos de manifests da unidade. |
| `status` | `proposed` para proposta registrada; `deployed` somente após o operador confirmar implantação. Validação não muda o status nem verifica essa evidência. |

O catálogo guarda referências, sem copiar manifests ou inventário do consumidor.
O validador verifica estrutura, sintaxe e unicidade de IDs. Ele não consulta o
GitHub para confirmar a existência do commit/path, nem compara IDs e URLs com o
contrato remoto. Essa conferência faz parte da revisão de publicação. Novas
unidades começam como `proposed`.

## Validação local

Em Linux/WSL2, com Python 3.12 e ambiente independente deste repositório:

```sh
uv sync --frozen
uv run --frozen python -B scripts/validate.py service templates/service.contract.json
uv run --frozen python -B scripts/validate.py catalog catalog/services.json
make lint
make test
make validate
```

Para um consumidor já disponível localmente, use seu path JSON no lugar do
template. O comando aceita `service PATH` ou `catalog PATH`, retorna 0 para
documento válido e 1 para documento inválido, ausente ou ilegível. Uso incorreto
da CLI retorna 2. Erros imprimem somente categoria fixa, sem valores de entrada,
nomes de campos fornecidos pelo usuário, paths privados ou mensagens brutas de
exceção. Chaves JSON duplicadas e números não finitos são recusados.

A CLI lê apenas o documento indicado e os schemas versionados locais, não faz
I/O de rede, não escreve arquivos e não altera runtime. A opção Python `-B`
também evita bytecode durante a execução. Dependências são resolvidas na
preparação por `uv sync --frozen`, com versões e hashes em `uv.lock`; a instalação
pode precisar de rede, mas validar os documentos após a instalação é offline.

Testes usam documentos temporários e executam a CLI real. Eles não comprovam
ACLs, firewall, espaço livre, disponibilidade de GPU, existência de manifests,
isolamento de VMs, execução de probes ou recuperação física. Valores sensíveis
podem imitar a sintaxe de nomes; a ferramenta não substitui revisão de segredos.

## Recuperação e evolução

O runbook consumidor deve fechar operações dependentes de storage quando a
base física estiver indisponível, preservar pausas manuais e só retomar após a
validação das precondições. A plataforma coordena USB, energia, mounts e exports;
o consumidor coordena suas filas, importações, exclusões e reconciliação. Uma
autoridade coordena cada incidente. Um contrato não pode delegar permissões que
o operador não tenha concedido.

Os schemas v1 são uma interface publicada: mudanças incompatíveis exigem nova
versão e migração explícita dos consumidores. A referência da plataforma no
consumidor deve fixar um commit que já contenha o schema. Depois se publica o
commit consumidor contendo o contrato; só então o catálogo aponta para esse
commit. Essa sequência evita referências circulares entre commits novos.
