# Órbita: operação do homelab

O portal privado reúne as aplicações, as VMs, os discos e as atividades. O login
continua usando a identidade Proxmox, inclusive realm e segundo fator quando
habilitado. O portal não tem uma senha administrativa independente.

## Aplicações e VMs

Os cards mostram serviço, VM, estado do container e consumo observado. O botão
**Abrir** usa o endereço privado publicado; componentes internos sem interface
publicada aparecem identificados, sem links para portas inacessíveis. O estado
do container e o healthcheck são informações diferentes. Ausência de healthcheck
não significa que a aplicação passou por um teste de saúde.

Em **Serviços**, as ações iniciam, param ou reiniciam um container existente.
Não criam containers nem alteram imagens, volumes ou configurações. O catálogo
é instalado pelo operador em cada VM. O painel não recebe comandos shell,
nomes de containers ou caminhos arbitrários do navegador.

A sessão humana precisa de `VM.Audit` e `VM.GuestAgent.Unrestricted` no alvo.
O QEMU Guest Agent executa somente o helper fixo
`/usr/local/libexec/homelab-runtime.py`. Esse privilégio Proxmox permite execução
ampla por outras ferramentas: concedê-lo somente a administradores confiáveis.
O helper e `/etc/homelab-runtime.json` pertencem a root; o catálogo define a VM,
os rótulos Compose e os serviços permitidos. O helper compara a revisão vista
pelo usuário antes de agir, preserva os entrypoints de proteção existentes e
confere identidade, filesystem e modo das montagens antes de iniciar/reiniciar.
Parar um serviço continua possível se o armazenamento estiver indisponível.

Quando há healthcheck Docker, o helper espera sua confirmação por até 40 segundos.
Nos serviços core protegidos, o catálogo também fixa o comando do processo nativo
esperado, comparado ao filho do guard. Sem healthcheck, a confirmação comprova
o processo em execução; não equivale a um teste funcional completo da aplicação.
Se não conseguir confirmar a prontidão, a operação permanece em reconciliação,
sem repetir o comando.

Cada ação exige sessão, origem correta, CSRF e chave de idempotência. A intenção
fica no journal antes do envio. Se a resposta se perder, o portal não repete
automaticamente o comando. Consulte o estado atual antes de decidir uma nova
ação. O próprio container do painel é protegido para preservar o canal de
controle; sua manutenção continua disponível pelo console Proxmox.

O catálogo não retoma automaticamente a automação de mídia. Maintenance,
receipts, holds, leases e o guard de storage continuam valendo. A API de mídia
parada não é iniciada pela coleta. A VM edge desligada é mostrada como desligada,
sem tentar executar comandos nela.

## Memória e observabilidade

O portal separa a memória configurada na VM da memória atribuída a ela pelo
Proxmox. A visão de serviços inclui `MemAvailable` do guest e memória de trabalho
dos containers, descontando cache de arquivo inativo quando disponível. Esses
números não são somáveis entre camadas. A memória residente da VM pode incluir
cache reutilizável pelo guest. O restante calculado pelo Proxmox não é rotulado
como `MemAvailable` do host.

O Grafana tem quatro dashboards ligados entre si: visão geral, VMs, discos e
serviços. O Grafana mostra séries e alertas; as ações administrativas ficam no
portal. Plugins de fontes não utilizadas ficam desabilitados no Compose, com a
fonte Prometheus preservada. Não se reduziu a RAM das VMs nem se descartaram
caches para produzir números artificialmente menores.

Veja o [inventário físico](physical-storage-inventory.md) para a distinção entre
os discos do Proxmox, os storages de VMs e o HD entregue ao core.

## Credenciais

Os acessos administrativos das aplicações usam o usuário solicitado pelo
proprietário. A relação de acesso fica somente na documentação privada; senhas,
API keys e cookies não entram neste repositório. Proxmox e o portal preservam o
login anterior. Contas comuns do Jellyfin e contas do sistema operacional não
foram alteradas. O Seerr utiliza a conta administrativa vinculada ao Jellyfin.

## Instalação e reversão

Instalar o helper nas VMs gerenciadas com modo `0755`, root:root; instalar o
catálogo com modo `0600`, root:root. Fixar hostname, rótulos Compose, montagens
e URLs publicados a partir do inventário real. Não descobrir novos alvos de
escrita automaticamente. O helper não é daemon nem instala units.

Antes de atualizar a plataforma, preservar os arquivos, `.env`, imagem anterior
e uma cópia consistente do journal fora do Git. Validar os dois Compose; construir
a imagem de controle e recriar somente controle, coletor e Grafana. Conferir
login/logout, os discos, a coleta de serviços e uma ação reversível em componente
sem impacto no acervo. Para reverter código, restaurar fontes e imagem anteriores;
preservar o journal atual para não perder as operações realizadas depois do backup.

Referências: [API do agente Proxmox](https://github.com/proxmox/qemu-server/blob/master/src/PVE/API2/Qemu/Agent.pm),
[plugins desabilitados no Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/#disable_plugins).
