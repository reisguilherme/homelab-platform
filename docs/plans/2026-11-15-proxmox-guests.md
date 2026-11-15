# Preparação das VMs do Proxmox

Desenho aprovado: [to-be](../architecture/to-be.md). O proprietário autorizou
prosseguir com a implementação e a indisponibilidade. Esta etapa prepara e,
quando houver acesso ao host, cria core, playback e edge. Não restaura mídia.

## Decisões desta execução

- Ubuntu 24.04 LTS amd64 cloud-image datada, checksum assinado pela Canonical.
- Core: 4 vCPU, 6 GiB RAM, 160 GiB disco; playback: 4/4/80; edge: 1/1/16.
  Total de discos 256 GiB, reserva inicial de 92,82 GiB no thin pool medido.
  Playback recebeu 16 GiB adicionais após a análise final dos metadados.
- Somente `local-lvm` no SSD de sistema autorizado. Nenhum disco físico é
  formatado, montado ou passado a uma VM nesta etapa.
- Bridge privada, NAT somente de saída, SSH por salto no Proxmox. A bridge de
  gestão existente permanece intacta. Endereços/IDs/identidades reais são privados.
- Firewall legado por VM, entrada/saída DROP, IP/MAC fixos, IPv6 bloqueado.
  Core pode alcançar API playback; playback pode alcançar NFS core. Edge fica
  sem fluxo de aplicação até existir listener público separado do Jellyfin.
- Firewall de host fica desabilitado inicialmente para preservar a gestão;
  as VMs bloqueiam acesso à gestão. Restrição da gestão pela LAN continua gap.
- Gerador local produz configurações e comandos para revisão; não executa
  deploy. Inventário fresco e aplicação assistida são etapas distintas.
- Sem autostart inicial, DNAT, portas no roteador, K3s, RTX ou novas units do host.

## Tarefas e verificações

1. Registrar orçamento do estado capturado, validar imagem oficial, conferir
   acesso e inventário. Identidade física do SSD prevalece sobre `/dev/nvmeX`.
2. Escrever testes de rejeição de sobreposição de rede, IDs/MACs/IPs duplicados,
   recursos excedidos, serial/storage incorretos e inventário desatualizado.
   Implementar gerador de bridge, regras e cloud-init sem execução implícita.
3. Conferir sintaxe PVE instalada, salvar configurações afetadas em área privada,
   preparar rollback antes de alterar rede/firewall. Criar somente VMs novas.
   Uma falha preserva volumes existentes; não fazer cleanup destrutivo automático.
4. Provar segunda sessão de gestão, cloud-init/QGA, confiança SSH via QGA e
   conexões reais positivas/negativas. Verificar persistência e anti-spoofing.
5. Revisar a mudança completa, rodar lint/test/validate em Python 3.12/Linux,
   publicar em `refactor` e atualizar o estado conforme evidências reais.

## Estado da execução

Concluídos em 15/11/2026: imagem autenticada, preflight, criação das três VMs,
rede/firewall, confiança SSH pelo QGA e testes de conectividade. O timeout
inicial ocorreu antes de qualquer mutação; o proprietário restabeleceu o host.

O aceite inclui 21 conexões TCP, DNS/HTTPS nos três guests e contadores de DROP
para IP/MAC forjados, ARP, VLAN 0/100, 802.1ad e IPv6. Depois de reiniciar o
Proxmox, as VMs iniciaram na ordem configurada; filtros, NAT, SSH e HTTPS
persistiram, e os 21 testes de conexão passaram novamente. A suíte local
Python 3.12/Linux passou com 94 testes; lint e validação dos contratos também.

Decisões tomadas durante a execução:

- O parser instalado exige `bridge-fd` mínimo 2. Corrigido antes de levantar
  a bridge; STP permanece desabilitado.
- O firewall legado aceita ESTABLISHED antes dos filtros por VM. Guards em
  raw/PREROUTING verificam IP/MAC no tap antes do conntrack; Ethernet bloqueia
  tags e remetentes MAC/ARP inválidos nos caminhos INPUT e FORWARD.
- O contador de 802.1Q recebeu também os quadros 802.1ad no backend observado.
  O aceite usa os deltas capturados de ambos os filtros de tag, sem confundir
  ausência de incremento em uma regra com sucesso ou falha do isolamento.
- `onboot` foi habilitado somente após os testes iniciais, com ordem core,
  playback, edge. Isso inicia VMs; não comprova readiness de aplicações.

Discos de mídia, restauração, exports NFS, GPU e publicação permanecem para a
próxima etapa. O [runbook](../runbooks/proxmox-guests.md) registra o resultado
e os limites; perfis, inventários e logs brutos permanecem privados.
