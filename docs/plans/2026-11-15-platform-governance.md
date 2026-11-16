# Platform Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Track execution with the checkboxes below.

**Goal:** Entregar API, portal, telemetria e controle privado de VMs na plataforma, independentes do projeto de mídia.

**Architecture:** FastAPI serve uma interface JavaScript/CSS da mesma origem e opera a API HTTPS Proxmox com a identidade humana delegada. Uma VM homelab-control hospeda essa aplicação, Prometheus e Grafana, com estado em SSD local. Proxmox mantém autoridade de ACL e o console independente de recuperação.

**Tech Stack:** Python 3.12, FastAPI, HTTPX, SQLite, JavaScript ES modules, CSS, Docker Compose, Proxmox VE, Prometheus e Grafana.

**Spec:** [Operação e governança](../architecture/operations.md), [orçamento](../architecture/to-be.md#orçamento-inicial-de-recursos) e [observabilidade](../observability.md). Este plano executa o requisito confirmado de controle completo; os itens ainda não aceitos em runtime permanecem pendentes.

**Estado em 16/11/2026:** API/portal, Prometheus e Grafana implantados com TLS
privado. Ensaios reais aceitaram CRUD/ACL/TOTP, coleta, alertas locais e reboot
do controle. Portal e Grafana passaram no navegador real em desktop/mobile.
A suíte final teve 236 testes
pytest aprovados em WSL/Python 3.12, Ruff check/format em 21 arquivos e dez
testes Node. Os checkboxes abaixo indicam evidência observada; não atestam
execução RED de cada nome de teste originalmente sugerido.

## Global Constraints

- Não iniciar Compose monolítico, modificar acervo ou usar dados reais como fixtures.
- Mídia é somente leitura na playback; scans suspensos enquanto o acervo estiver parcial.
- Não criar CI/CD, releases, gerenciador de backups ou units novas no Proxmox.
- Não formatar discos existentes, substituir fstab, ativar RTX ou abrir portas no roteador.
- Segredos ficam no ambiente privado da implantação, sem `*_FILE`; nenhum segredo em Git.
- API usa HTTPS Proxmox com CA e hostname verificados, destino fixo e métodos tipados.
- API não recebe chave root SSH, shell arbitrário, QGA genérico ou socket Docker.
- Sessão humana não é credencial do coletor; Grafana não recebe poderes de mutação.
- `homelab` identifica a plataforma; `mediaserver` identifica o projeto consumidor.
- Recursos aplicados: homelab-control 2 vCPU, 2 GiB RAM e disco virtual de 24 GiB; core reduzido 6→4 GiB após medição e parada limpa.
- A soma permanece 11 GiB para guests; conservar 3 GiB de orçamento do host e cerca de 1,49 GiB de margem.
- Thin pool exige preflight de uso físico, metadata, compromisso lógico e folga; a antiga reserva de 20% pelo tamanho máximo não continua válida.
- Nenhuma operação é bem-sucedida somente porque recebeu HTTP 200/202 ou UPID.

## Review Focus

- Timeout após criação pode ter criado a VM: persistir intenção e reconciliar sem repetir.
- ACL revogada durante uma sessão deve negar a próxima operação; não confiar em capability de login.
- TFA incompleto, Origin falso e CSRF ausente não criam sessão ou mutação.
- Exclusão com configuração alterada, passthrough ou dependência protegida não remove recursos.
- Reinício de API, coleta sem dados e core indisponível não fabricam sucesso ou saúde.

## 1. Decisões e alternativas

| Alternativa | Resultado | Decisão |
|---|---|---|
| Somente links para Proxmox/Grafana | Reutiliza consoles, mas não entrega API e fluxo central de operações pedidos | Substituída como solução principal; consoles continuam como complemento |
| Portal dentro do core de mídia | Evita nova VM, mas acopla governança ao consumidor e ao seu ciclo de falha | Descartada para esta entrega |
| API/portal em homelab-control com API Proxmox delegada | Separa posse, entrega ações próprias e mantém a autorização nativa | Escolhida; conta de memória realocada, sem token administrativo global |
| Kubernetes/SSO externo/portal completo de datacenter já | Aumenta dependências antes de existir capacidade e identidade externa configuradas | Adiar; a primeira entrega usa Compose e login Proxmox |

O portal inicial cobre inventário, criação por perfil, CPU/RAM, energia, exclusão
e ACL por VM. Hardware avançado e console usam links para Proxmox. Contas Linux,
contas de aplicativos e rede são domínios distintos; não prometer que uma ACL da
VM configure os três. Não adicionar um novo cadastro de senhas humanas.

## 2. Fronteiras e autenticação

Fluxo: navegador → HTTPS privado do portal → API → HTTPS Proxmox. A URL do
Proxmox, CA pública e hostname esperado são configuração do operador, não
parâmetros de uma requisição. Certificado e nome devem ser validados; o endpoint
privado é fixo. Publicar só em loopback/túnel ou rede de gestão filtrada, com
origem HTTPS definida e testada. Não flexibilizar cookies/TLS para acelerar o teste.

`POST /api/v1/session` recebe username e password; TOTP usa a etapa separada
de desafio descrita abaixo. Backend envia para `POST /access/ticket`, nunca
salva senha e nunca devolve ticket/CSRF Proxmox. Sessão usa cookie opaco aleatório
de pelo menos 256 bits, `HttpOnly; Secure; SameSite=Strict; Path=/`, prazo ocioso
de 30 minutos e absoluto de 2 horas, sem extensão além da validade do ticket.
Uma única instância/worker mantém sessões em memória. Reinício exige novo login.

Resposta Proxmox com `NeedTFA` guarda desafio no servidor por no máximo 5 minutos
e devolve apenas identificador opaco. `POST /api/v1/session/tfa` recebe esse ID e
código TOTP; o adapter utiliza o formato confirmado na API instalada e só cria
sessão quando o desafio termina. Limitar tentativas de login/desafio. WebAuthn,
recovery codes e outros métodos ficam explicitamente não suportados enquanto
não tiverem implementação e teste; o usuário conserva o console nativo.

Login também verifica origem exata e content-type JSON. Sessão autenticada
ganha token CSRF próprio de pelo menos 256 bits; todas as mutações exigem
`X-CSRF-Token`. Sem CORS aberto. Logout invalida a sessão local e apaga o cookie;
não alegar que revoga todos os tickets Proxmox já emitidos. Expiração, erro de
autenticação upstream e reinício encerram a sessão do portal.

PVEACL é fonte de autorização em cada operação. Usar ticket da própria pessoa
para leituras e mutações; token de coleta nunca autoriza operação humana.
Auditoria pertence ao usuário e aos alvos que ele ainda pode consultar; acesso
global requer privilégio pertinente conferido na API instalada. O servidor não
revela configuração bruta de VM: cloud-init, args e dispositivos podem conter
segredos. Usar DTO de campos permitidos.

## 3. Contrato HTTP inicial

Prefixo fixo: `/api/v1`. JSON usa camelCase. Data/hora ISO8601 UTC; IDs de VM
inteiros positivos. Erro uniforme: `{"error":{"code":"...","message":"...","requestId":"..."}}`,
sem traceback ou resposta upstream bruta. Usar 401 sem sessão, 403 para
autorização/origem/CSRF, 409 para conflito/estado, 422 para campos inválidos e
503 para upstream/coleta indisponíveis.

| Método e rota | Entrada | Saída e efeito |
|---|---|---|
| GET /session | Cookie, se houver | `authenticated`, `user`, `csrfToken`; não inclui credencial PVE |
| POST /session | `username,password,otp?` | Sessão ou `challenge:{kind:"totp",id,expiresAt}` |
| POST /session/tfa | `challengeId,code` | Sessão somente após TFA completo |
| DELETE /session | Sessão + CSRF | 204; sessão local invalidada |
| GET /overview | Sessão | `collectedAt,sourceState,nodes,capacity,alerts` |
| GET /profiles | Sessão | Perfis de criação permitidos, limites e readiness resultante |
| GET /vms | Sessão | `items,collectedAt,sourceState`, filtrados por ACL |
| GET /vms/{vmid} | Sessão | VMDTO com digest, recursos, pendências, dependências e capabilities |
| POST /vms | `name,project,profileId,cores,memoryMiB,diskGiB` | Operação; perfil fixa node/storage/bridge/base permitidos |
| PATCH /vms/{vmid}/resources | `cores,memoryMiB,expectedDigest` | Operação; estado concorrente é conflito |
| POST /vms/{vmid}/actions | `action,expectedDigest,confirmation?` | `start,shutdown,reboot,stop`; stop é força explícita |
| POST /vms/{vmid}/deletion-preview | Sessão + CSRF | `intentId,expiresAt,name,digest,impact,allowed,blockers` |
| DELETE /vms/{vmid} | `intentId,confirmationName` | Operação; revalidar ACL, digest, dependências e intenção |
| GET /vms/{vmid}/acl | Sessão | `items,digest`; entradas explícitas/herdadas e sua origem |
| PUT /vms/{vmid}/acl | `principalType,principal,role,propagate,expectedAclDigest` | Operação; usuário/grupo e papel existentes |
| DELETE /vms/{vmid}/acl | `principalType,principal,role,expectedAclDigest` | Operação; somente ACL explícita desse path |
| GET /operations/{id} | Sessão | Estado sanitizado da operação autorizada |
| GET /audit | Sessão; paginação limitada | Eventos sanitizados visíveis à identidade |

VMDTO: `vmid,node,name,project,pool,tags,status,cores,memoryMiB,diskGiB,digest,
pending,dependencies,capabilities,collectedAt`. Capabilities são por objeto e
ação; servem para interface, sem substituir a validação no servidor.

Mutações de recurso exigem `Idempotency-Key` de 16–128 caracteres ASCII seguros.
A chave é vinculada a ator, ação, alvo e hash dos parâmetros normalizados.
Mesma chave com outro conteúdo retorna 409; mesma operação retorna o registro
original. Resposta 202: `operationId,state,task?`, onde task contém apenas node
e UPID autorizados. Estados: `accepted,submitted,running,succeeded,failed,
reconciling`. Timeout após envio não é failed definitivo nem motivo para repetir.

Prévia destrutiva expira em 5 minutos, é vinculada ao ator, alvo e digest e só
pode ser consumida uma vez. Nunca incluir discos físicos, usar purge amplo ou
remover recursos externos como efeito colateral. Mudança desde a prévia exige
nova prévia. Recusar VM de controle, passthrough e dependências protegidas nessa
primeira API; o console mantém operações avançadas com procedimento próprio.

Criação inicia desligada por padrão. Perfil define se entrega apenas hardware
para instalar SO ou clone de imagem já preparada; UI mostra essa diferença.
VMID, storage, bridge, rede, imagem e limites vêm de configuração permitida no
servidor. Não aceitar path de imagem, argumentos QEMU ou hostname upstream do
navegador. Validar capacidade física e compromisso antes de enviar a operação.

ACL usa path fixo `/vms/{vmid}`; não receber path genérico. Mostrar ACL herdada
sem alterá-la nesse endpoint. Mudança é diferencial e acompanha leitura após
gravação; não substituir toda a ACL com snapshot antigo. Privilégios e semântica
exatos são conferidos no schema da versão instalada antes de habilitar a rota.

## 4. Organização de arquivos

| Caminho planejado | Responsabilidade |
|---|---|
| `services/control/app.py` | FastAPI, rotas explícitas e assets da mesma origem |
| `services/control/models.py` | DTOs de entrada/saída e campos permitidos |
| `services/control/auth.py` | Sessões em memória, CSRF, origem e desafio TFA |
| `services/control/proxmox.py` | HTTPX, TLS, adapter dos endpoints permitidos e erros sanitizados |
| `services/control/operations.py` | Intenção, idempotência, prévias, tarefas e reconciliação |
| `services/control/audit.py` | SQLite e transações de operações/eventos, sem credenciais |
| `services/control/static/index.html` | Estrutura acessível do portal |
| `services/control/static/app.js` | Módulo vanilla, formulários e acompanhamento de tarefas |
| `services/control/static/style.css` | Layout responsivo e estados visuais |
| `services/control/Dockerfile` | Imagem sem root e sem ferramentas de gestão do host |
| `compose.control.yaml` | API/portal privados e limites; Compose separado de consumidores |
| `deploy/observability/` | Coleta, dashboard de infraestrutura e regras locais |
| `tests/test_control_*.py` | Autorização, adapter, operações e integração com PVE simulado |
| `tests/test_observability.py` | Isolamento, fontes e limites da stack compartilhada |

FastAPI/HTTPX e dependências ficam pinados no lock do repositório. SQLite está
em SSD local. Não adicionar Redis, Celery, banco servidor ou frontend com build
sem necessidade. O processo da API não inicia shell ou ferramentas Proxmox.

## 5. Execução e verificações

### Tarefa 1 — identidade e capacidade

- [x] Atualizar gerador/teste de nomes para mediaserver-core/playback/edge e
  classificação separada; preservar IDs, IPs e hostnames Linux.
- [x] Ajustar perfis privados que validam o nome da VM; confirmar supervisor
  após a mudança, sem renovar saúde por mera correspondência de nome.
- [x] Medir RAM/pressão do core, host e pool físico/metadata; registrar decisão
  sanitizada para realocação 6→4 GiB e novo guest 2 GiB.
- [x] Preparar perfil privado da VM de controle com 2 vCPU/2 GiB/24 GiB,
  cloud image previamente verificada, SSD virtual novo e rede privada filtrada.
- [x] Testar os geradores com fixtures; provisão real e estado seguem evidência
  privada, sem confundir teste local com criação de VM.

### Tarefa 2 — sessão e leitura segura

**Interfaces:** `create_app(settings, proxmox, audit)` monta aplicação testável;
`ProxmoxClient` aceita destino fixo e CA; `SessionStore` guarda somente memória
e usa relógio injetável. Backend e UI seguem o contrato da seção 3.

- [x] Cobrir origem/CSRF/TFA/expiração e DTOs sem segredos na suíte de auth/API.
  Nomes e ordem RED sugeridos no plano inicial não são alegados como recibo.
- [x] Implementar auth, DTOs, adapter TLS e leitura de inventário/perfis/VM/ACL.
  Capturar schema oficial instalado para mapear endpoints e permissões; manter
  a captura bruta privada, versionando apenas fixtures sintéticas.
- [x] Executar `uv run --frozen pytest tests/test_control_auth.py tests/test_control_api.py -q`
  e `uv run --frozen ruff check services/control tests/test_control_*.py`.
  Resultado necessário: todos passam, sem verificação TLS desabilitada.
- [x] Aceitar cinco checks TOTP reais: desafio sem sessão, código incorreto
  negado e consumido, correto com cookie Secure/ACL e logout; identidade de
  ensaio removida. Login/TOTP usam POST e envio desabilitado até JS pronto.

### Tarefa 3 — operações duráveis

**Interfaces:** `OperationStore.begin(actor,key,action,target,parameters)`
registra intenção ou recupera operação idempotente; o serviço de operações
usa somente métodos explícitos do adapter. A estrutura persistida não contém
senha, ticket, CSRF ou body upstream.

- [x] Manter testes para autorização revogada, conflito de digest, retry de
  criação, timeout após envio, tarefa com exitstatus de erro, SQLite indisponível,
  restart do processo, passthrough protegido e tentativa de mudar ACL ancestral.
- [x] Implementar CRUD, CPU/RAM, energia e ACL da seção 3.
  Auditoria é gravada antes de mutações; GET de estado não repete envio.
- [x] Implementar reconciliação com UPID e consulta do objeto. Ambiguidade sem
  prova permanece explícita; logout não perde o registro nem autoriza retry.
- [x] Executar `uv run --frozen pytest tests/test_control_operations.py -q`.
  Validar que uma mesma intenção gera no máximo uma chamada mutável no mock.
- [x] Revisar schemas e negações antes do ensaio real em VM descartável.
- [x] Aceitar 14 checks reais, oito operações concluídas: criação idempotente,
  CSRF negado, RAM 384→512 MiB, ACL add/remove, leitor sem mutação/visibilidade
  da mídia, start/stop, exclusão, auditoria e logout. VM descartável removida.
- [ ] Ensaiar shutdown/reboot ACPI pelo portal em guest com SO. A VM de aceite
  tinha 1 vCPU, 512 MiB e disco de 4 GiB, sem NIC/SO, e não cobre ACPI.

### Tarefa 4 — portal utilizável

**Interfaces:** apenas rotas da seção 3. UI nunca recebe credencial upstream,
nunca calcula autorização como autoridade e não interpola dados em innerHTML.

- [x] Criar tela de login/TOTP, visão geral, lista/detalhe de VMs, formulário de
  criação, recursos, ações de energia, prévia de exclusão, ACL e auditoria.
- [x] Usar labels e foco corretos, texto de erro concreto, estados sem dados e
  pendente; desabilitar reenvio local enquanto preserva idempotência no backend.
- [x] Acompanhar operações até resultado real; atualizar estado após sucesso,
  sem apresentar 202 como conclusão. Renovar leitura após conflito 409.
- [x] Validar no navegador desktop e largura móvel contra API sintética: login,
  acesso negado, formulário, confirmação, tarefa pendente, timeout e logout;
  onze grupos de cenários e dez testes Node aprovados.
- [x] Links para Proxmox/Grafana usam destinos permitidos e não contêm tokens.
- [x] Concluir aceite visual no navegador com portal/Grafana e dados reais:
  portal em leitura, visão geral, VMs/recursos/ACL/atividades e logout, sem
  mutações. Grafana com sessão própria e 22 consultas sem erro, 21 com séries;
  alertas firing ausentes mostram “Sem dados”. Desktop/390 px sem overflow
  ou exceções; capturas privadas.

### Tarefa 5 — observabilidade e runtime

- [x] Integrar coletor PVE somente leitura com ACL/token separado e TLS válido;
  coletar a cada 30 s. Não reutilizar tickets humanos nem abrir exporters públicos.
- [x] Adicionar dashboard de nó/VM/storage/tarefas/coleta e regras de dados
  ausentes, espaço físico e falha de operações. Fontes indisponíveis ficam
  desconhecidas; não inventar SMART, temperatura ou energia na API PVE.
- [x] Manter limites Prometheus 512 MiB/Grafana 384 MiB e retenção 7 dias/4 GiB;
  API/coletor começam com teto conjunto 384 MiB e logs limitados.
- [x] Validar Compose com fixture e executar `uv run --frozen pytest tests/test_observability.py -q`.
- [x] Provisionar homelab-control por imagem verificada e alocação de disco
  virtual novo, sem mkfs/particionamento de dispositivos existentes. Não alterar
  o segundo SSD preservado para contornar a margem do thin pool.
- [x] Implantar HTTPS privado, CA, regras de rede e Compose; confirmar negações
  a partir de media edge/playback e acesso direto Proxmox independente.
- [x] Aceitar seis targets ativos: quatro guests, coletor PVE e Prometheus;
  22 painéis provisionados, sem inferir aceite visual desse provisionamento.
- [x] Interromper coletor e exporter do controle por 150 s, observar
  `GuestExporterUnavailable` e `ProxmoxCollectionUnavailable` firing,
  restaurar fontes e confirmar resolução/targets ativos.
- [x] Reiniciar controle: chave SSH preservada, novo boot ID, cookie anterior
  negado, 34 eventos/nove operações SQLite e banco Grafana preservados;
  quatro containers sem OOM e seis targets ativos. Autostart em ordem 5,
  com 20 s de partida e 60 s de desligamento, antes dos convidados de mídia.
- [ ] Medir consumo sob carga. Canal
  externo e sonda independente permanecem pendentes de integração e teste.
- [x] Registrar resultados e limites no estado de implementação.
- [ ] Publicar na branch refactor após revisão de segredos, testes e diff.

## 6. Limites remanescentes

A API inicial não configura usuários Linux, contas de aplicação, todo hardware
Proxmox ou rede física; esses controles continuam nos consoles específicos.
Histórico local não é auditoria imutável; SQLite ainda não tem poda automática.
Reconciliação sem UPID/prova suficiente exige investigação manual e não libera
reenvio. CPU/RAM usam digest upstream; energia, exclusão e ACL conservam janela
de concorrência com alterações externas ao portal. Sem outro domínio físico não há
monitoramento da própria queda total. Nobreak, reintegração USB completa,
consolidação de discos e capacidade para dez reproduções continuam com seus
aceites próprios. Ter portal operacional não encerra essas lacunas.

## Referências primárias

- [Autenticação e TFA](https://github.com/proxmox/pve-access-control/blob/master/src/PVE/API2/AccessControl.pm)
- [ACLs e tokens](https://github.com/proxmox/pve-docs/blob/master/pveum.adoc)
- [Tarefas e resultado](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Tasks.pm)

Essas fontes orientam o desenho. O adapter precisa conferir o schema da versão
instalada, especialmente capacidades de token, ACL, digest, criação e TFA.
