# Governança privada: operação e aceites

Este roteiro acompanha a implantação na **homelab-control**, separada das
VMs de mídia. O [estado canônico](../implementation-status.md#plataforma-de-controle)
registra os fatos aceitos. Em **16/11/2026**, VM, rede, nginx TLS, API, portal,
Prometheus e Grafana estão operantes. CRUD/ACL, TOTP, coleta, alertas locais,
reboot do controle e navegação desktop/mobile passaram em ensaios reais.

## Base entregue

- VM criada de imagem Ubuntu com hash previamente verificado: 2 vCPU,
  2 GiB de RAM e disco virtual de 24 GiB. Tags identificam plataforma,
  governança e observabilidade.
- Core reduzido de 6 para 4 GiB após medição, NFS desmontado normalmente na
  playback e desligamento gracioso. O retorno preservou chave SSH, UUID do
  HD, NFS e recibo; Jellyfin retornou saudável com catálogo preservado.
- QGA, SSH e cloud-init do controle conferidos; único aviso foi a depreciação
  do campo `user` como string gerado pelo Proxmox.
- Nginx TLS ativo. A CA existente do Proxmox assinou o certificado e a chave
  privada permaneceu no guest. Origem e porta do túnel ficam na ficha privada;
  usar exatamente o nome/endereço coberto pelo certificado, sem desabilitar TLS.
- Exporters de nó instalados nos quatro guests. Controle → 9100 dos quatro
  guests permitido; controle → SSH do core/Proxmox negado. Edge/playback →
  controle nas portas 22, 8080, 8443 e 9100 negado. Esses checks não aceitam
  automaticamente todos os demais fluxos de rede. A conferência TCP final
  incluiu negações de edge/playback ao controle em 22, 3080, 8080, 8443, 9090 e 9100.
- Credencial Proxmox de auditoria criada e mantida privada. Coleta RO não
  concede permissão de mutação às sessões humanas. A mesma identidade RO
  fornece a prova global de capacidade, sempre por chamadas GET; ações usam
  a sessão humana e suas ACLs atuais.
- Autostart do controle habilitado em ordem 5, com espera de partida de 20 s
  e desligamento de 60 s, antes de core 10, playback 20 e edge 30.

O orçamento permanece 11 GiB de guests. O preflight anterior à VM de controle
mediu 19,39% de uso físico do pool e 1,09% de metadata. O compromisso nominal
atual é de 312 GiB, mais poucos MiB de cloud-init, deixando cerca de 37 GiB
pelo tamanho completo. Reserva escolhida: 32 GiB; disco do perfil de ensaio:
4 GiB. Revalidar dados físicos, metadata e compromisso antes de alocar. Nenhum
disco ou filesystem existente do acervo foi formatado.

## Verificação e limites

O [plano aprovado](../plans/2026-11-15-platform-governance.md) define login
delegado, sessão/CSRF, API tipada, portal, auditoria e coleta. A UI passou em
dez testes Node e onze grupos de cenários em Chrome desktop e mobile com API
sintética: TOTP, formulários, 202 pendente, conflitos, negação de acesso,
reconciliação idempotente, prévia destrutiva, ACL, teclado e encerramento de
sessão. A suíte final teve 236 testes pytest aprovados em WSL/Python 3.12, além
de Ruff check/format em 21 arquivos. Esses checks não substituem os ensaios
reais abaixo. Recibos e screenshots ficam fora do Git.

Para repetir os checks locais da UI, sem servidor Proxmox:

```bash
node --test tests/control_ui.test.mjs
node tests/control_ui_fixture.mjs
```

A fixture imprime seu endereço loopback e usa somente dados sintéticos. O
[runner de navegador](../../tests/control_ui_browser.mjs) exercita os fluxos
contra ela; encerrar a fixture depois. Node é ferramenta de teste local, não
dependência do portal em produção: seus assets são servidos sem build.

O primeiro perfil cria **hardware desligado e sem NIC**. SO, rede, discos
avançados, passthrough e console permanecem no Proxmox. ACL da VM não cria
usuários Linux ou contas nos serviços. Tokens são somente consultados na UI;
ACL parcial não representa toda a herança de acesso.

O lock do portal não abrange alterações externas pelo console/API Proxmox.
CPU/RAM usam digest upstream; energia, exclusão e ACL mantêm uma janela entre
revalidação e execução. Coordenar essas ações com o console, especialmente
durante a confirmação destrutiva. O portal recusa VMs protegidas, passthrough
e recursos fora dos perfis permitidos; não é um editor genérico de hardware.

Resposta 202 ou UPID representa uma solicitação em andamento. Confirmar tarefa
e estado observado antes de concluir. Timeout não autoriza nova intenção;
reconciliar a mesma chave. Criação sem resultado rastreável bloqueia novas
alocações no nó até prova ou investigação. O registro SQLite ainda não possui
poda automática: acompanhar espaço, sem confundir histórico local com backup.

## Ensaios reais concluídos

1. Quatorze checks de CRUD/recursos/ACL, com oito operações concluídas em VM
   descartável sem NIC/SO: criação idempotente, CSRF negado, RAM de 384 para
   512 MiB, concessão/revogação ACL, usuário de leitura sem mutação nem acesso
   às VMs de mídia, start/stop, exclusão, auditoria e logout. A VM foi removida.
2. Cinco checks de TOTP: matrícula efêmera, desafio antes de sessão, código
   errado negado consumindo o desafio, código correto com cookie Secure e
   ACL respeitada, logout. Credenciais humanas seguem POST HTTPS; formulários
   só habilitam envio após handlers e leitura da sessão. O proxy não registra
   query strings. Contas e permissões do ensaio foram removidas.
3. Seis targets reais ativos e 22 painéis provisionados. Interrupção de coletor
   e exporter do controle por 150 s disparou `ProxmoxCollectionUnavailable` e
   `GuestExporterUnavailable`; restauração resolveu os alertas. Nenhum alerta
   estava ativo na observação final. Canal externo não foi testado.
4. Reboot da VM de controle preservou chave SSH, 34 eventos/nove operações
   SQLite e banco Grafana, mudou boot ID e invalidou cookie anterior. Quatro
   containers retornaram sem OOM e os seis targets voltaram a ficar ativos.
5. Navegador real em desktop e 390 px: portal com login de leitura, visão
   geral, VMs/recursos/ACL, atividades e logout, sem mutações ou erros de UI.
   Grafana com sessão própria, 22 painéis/consultas sem erro; 21 tinham séries
   e a consulta de alertas firing vazia exibiu “Sem dados”. Não houve overflow
   ou exceções; capturas e credenciais ficam privadas.

## Aceites e manutenção restantes

- Ensaiar shutdown/reboot ACPI pelo portal em guest com SO; o start/stop da
  VM hardware-only não cobre esses caminhos.
- Medir consumo sob carga e definir manutenção de SQLite antes de crescimento
  sustentado. Retenção de sete dias/4 GiB é do Prometheus, não da auditoria.
- Manter investigação manual de resultado ambíguo sem UPID/prova suficiente,
  sem reenviar intenção. Falhas de timeout e concorrência têm testes sintéticos;
  não foram todas induzidas no Proxmox real.
- Escolher/testar canal externo e sonda fora do host. Reboot do controle e
  console independente não demonstram HA ou recuperação de falha do USB.
- Em novas alterações, repetir revisão e verificações pertinentes antes da
  publicação. Esta entrega foi publicada na branch `refactor`, no commit
  `a8f1c7305afdff5146a6d6e39253e1beac15bf81`.

Publicação de mídia, gestão LAN, GPU, recuperação física do USB, nobreak e
consolidação seguem pendentes. Esta etapa não altera a decisão do proprietário
sobre o backup final único no HD de 18 TB nem reexige cópia integral Windows.
