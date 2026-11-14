# Separação plataforma e projetos

Desenho aprovado pelo proprietário em 14/11/2026, seguido de autorização para
criar e publicar https://github.com/reisguilherme/homelab-platform.

O servidor passa a ser descrito por um repositório de plataforma e repositórios
consumidores. O homelab-mediaserver continua responsável pelo projeto de mídia;
outros projetos, como Immich, terão integração própria. O hardware e o runtime
atuais não mudam por causa da separação dos repositórios.

Alternativas: manter tudo em monorepo simplificaria mudanças atômicas, mas deixaria
menos explícita a independência dos projetos. Um repositório por container
fragmentaria a aplicação de mídia sem benefício. A escolha aprovada é plataforma
mais um repositório por projeto, com seus componentes internos juntos.

A plataforma possui arquitetura geral, contratos versionados, catálogo de
consumidores, configuração de Proxmox/rede/storage e observabilidade central.
Aplicações possuem código/configuração, manifests de implantação, métricas,
painéis específicos, testes e runbooks. O catálogo referencia commit e paths da
aplicação sem copiar seus manifests. Documentação e validação local são a primeira
etapa; políticas efetivas de rede/storage/ACL continuam necessárias.

Grafana/Prometheus são extraídos para cá. O exporter de mídia permanece no
consumidor. A integração inicial usa rede Docker interna dedicada entre projetos
no mesmo daemon, sem publicar Prometheus/exporter no host. Targets são opt-in e
privados. Isso não promete conectividade entre VMs: o caminho entre guests exige
endereço privado, firewall, autenticação/TLS conforme o caso e ensaio separado.

USB/energia/mount/export são responsabilidade da plataforma; bloquear downloads,
importações/exclusões e reconciliar estado de mídia pertence ao consumidor. O
código de recuperação fortemente acoplado não será movido mecanicamente.

Esta entrega não instala Proxmox, K3s ou VMs; não migra mídia; não inicia serviços;
não cria CI/CD, units ou infraestrutura de backup. A preparação será publicada em
refactor, preservando a orientação anterior. O destino remoto está vazio.
