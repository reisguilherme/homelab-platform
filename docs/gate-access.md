# Acesso SSH limitado e entrega do Gate

O Hub recebe a conexão TCP exclusivamente em `100.109.244.123:2222` pela interface `tailscale0`. O `systemd-socket-proxyd` encaminha o fluxo à VM 200 em `172.28.64.200:2222`. A VM 200 autentica a chave e apresenta sua própria chave de host OpenSSH. Confira a impressão digital de `/etc/ssh/ssh_host_ed25519_key.pub` da VM 200 por um canal administrativo antes da primeira conexão. O SSH administrativo continua na porta 22. O PVE e o Hub não recebem contas de entrega.

| Perfil | Acesso na VM 200 |
|---|---|
| `ssh-sftp-drop` | SFTP em `/batch`, para um único lote compartilhado pelos remetentes autorizados. O servidor NFS mapeia os pedidos ao UID/GID `1000:1000`. Cada conta SSH tem UID de sistema próprio e pertence apenas ao grupo de entrega. |
| `ssh-restricted` | Shell de diagnóstico em chroot somente leitura com `/bin/dash`, `/etc/os-release`, `/uptime` e `/loadavg`. Por exemplo, `read tempo resto </uptime; echo "$tempo"` exibe o tempo de atividade. O chroot omite ferramentas de rede, dispositivos, dados de mídia, credenciais e configuração do K3s. |

## Preparar os serviços

No checkout revisado de `main` em `pve01`, no diretório `infrastructure/ansible`, o comando `ansible-playbook -i inventory/hosts.yml playbooks/gate-access.yml` prepara a VM 200 e instala as unidades no Hub. O estado padrão mantém o transporte fechado, retira as chaves autorizadas pelo Gate e desmonta uma sessão de entrega anterior. A preparação funciona antes de conectar o disco. O login SSH comum da VM 200 recusa os dois grupos.

Para provisionar as contas e as chaves de um catálogo SOPS já revisado, execute `ansible-playbook -i inventory/hosts.yml playbooks/gate-access.yml -e gate_prepare_accounts=true`. O playbook encerra qualquer entrega anterior e retira a exportação NFS antes de reconciliar as identidades na VM 200. O daemon de entrega e o relé ficam parados. Por exemplo, a chave de `gustavo` fica em `/etc/ssh/gate-keys/gustavo`, sob propriedade de root. Uma nova execução nesse modo também retira as chaves removidas do catálogo. Para abrir uma entrega em outra execução, use os parâmetros do passo 4.

## Autorizar uma entrega

1. Vincule a identidade autorizada a `group:gate-delivery` no painel privado do Tailnet. Atribua `tag:hub` somente ao Hub e reserve seu `tagOwners` aos administradores. Conceda ao grupo apenas a porta TCP 2222 desse nó. O grant abaixo entra na política existente. O Tailscale soma grants e ACLs, portanto remova ou restrinja qualquer regra abrangente que já permita outras portas a esse grupo. [Tailscale grants e testes de política](https://tailscale.com/kb/1337/policy-syntax)

   ```json
   { "src": ["group:gate-delivery"], "dst": ["tag:hub"], "ip": ["tcp:2222"] }
   ```

   Gustavo também tem o perfil de leitura do HomeShip. Inclua sua identidade em `group:homelab-viewers` no Tailnet e autorize TCP 443 no Hub para esse grupo. O Authelia verifica o grupo da conta web para cada domínio. No editor do Tailnet, teste a identidade com `accept` para `tag:hub:2222` e `tag:hub:443` e `deny` para `tag:hub:22` e `tag:hub:8006`. Para um remetente que tenha apenas o perfil de entrega, a expectativa em 443 é `deny`. Se houver uma subnet route para a LAN, inclua `192.168.1.20:22`, `192.168.1.20:8006` e `172.28.64.200:22` nos destinos negados ao remetente.

   Para nós inscritos no Tailscale SSH com as tags administradas `tag:pve` e `tag:hub`, os grants de rede e o bloco `ssh` precisam autorizar o mesmo acesso. Mescle as entradas com a política privada da rede. No exemplo, `root` é a conta administrativa do PVE e `ubuntu` é a do Hub.

   ```json
   {
     "tagOwners": {"tag:pve": ["group:admins"], "tag:hub": ["group:admins"]},
     "grants": [
       {"src": ["group:admins"], "dst": ["tag:pve", "tag:hub"], "ip": ["tcp:22"]},
       {"src": ["group:homelab-viewers"], "dst": ["tag:hub"], "ip": ["tcp:443"]},
       {"src": ["group:gate-delivery"], "dst": ["tag:hub"], "ip": ["tcp:2222"]}
     ],
     "ssh": [
       {"action": "check", "src": ["group:admins"], "dst": ["tag:pve"], "users": ["root"]},
       {"action": "check", "src": ["group:admins"], "dst": ["tag:hub"], "users": ["ubuntu"]}
     ]
   }
   ```

   A política de Tailscale SSH se aplica quando o nó usa esse serviço. Na LAN administrativa, o acesso de recuperação do PVE segue o firewall Proxmox e o OpenSSH local.

2. Após verificar a identidade e receber sua chave pública, edite o arquivo cifrado `infrastructure/ansible/gate-accounts.sops.yaml` com o editor de SOPS a partir da raiz do repositório. A lista `accounts` contém, por pessoa, `name` (nome POSIX, por exemplo `gustavo`), `profile` e `key` (chave pública Ed25519 com comentário opcional). O playbook remove o comentário antes da instalação e recusa nomes já usados por contas que não administra. Cada pessoa tem nome e chave exclusivos. Publique o catálogo criptografado por GitOps.

3. Em `pve01`, o lote deve existir em `/mnt/gate-4tb/incoming/acervo-amigo-batch`, com UID/GID `1000:1000`, no ext4 de UUID `58a9af19-1ed0-4488-b08a-c34c35e5ebbf`. A única exportação do Gate atende a VM 200 por NFSv4/TCP. O cliente monta o lote diretamente em `/srv/gate-sftp/drop/batch` com `nosuid,nodev,noexec`. O restante do disco fica fora do chroot. O diretório subjacente pertence a root e a unidade do SSH depende da montagem. [Opções de exportação do NFS](https://man7.org/linux/man-pages/man5/exports.5.html)

4. Compare o tamanho do lote em bytes com `df -B1 --output=avail /mnt/gate-4tb` no PVE. O valor disponível considera a reserva do ext4. Com capacidade suficiente, ative `gate_delivery_network_enabled=true` no fluxo revisado de OpenTofu. Confira no plano as regras para VM 200 → PVE TCP 2049 e Hub → VM 200 TCP 2222. Com ACL do Tailnet e chaves verificadas, execute `ansible-playbook -i inventory/hosts.yml playbooks/gate-access.yml -e gate_access_open=true -e gate_tailnet_policy_verified=true`. A abertura falha se o disco, o caminho, a propriedade, o endereço do Hub ou as chaves divergirem.

5. Com a conta de entrega, conecte via `sftp -P 2222 gustavo@100.109.244.123`. Verifique a escrita de um arquivo de teste em `/batch`, sua propriedade no PVE e a recusa a comandos de shell. Para o diagnóstico use `ssh -T -p 2222 gate-diagnostico@100.109.244.123` e confira que `/batch` e `/etc/rancher` são inacessíveis. Cada conexão aceita fica em `journalctl -u gate-sshd.service` na VM 200, com usuário e impressão digital da chave. O endereço TCP registrado pela VM é o do relay.

## Revogar ou encerrar

Para revogação individual, retire a pessoa do grupo do Tailnet e do catálogo cifrado e reconcilie o playbook com o conjunto atualizado. Para encerrar a entrega, execute o playbook no estado padrão. Ele para o socket e conexões do relay, encerra o OpenSSH de entrega, desmonta o lote e retira o export. Desative as duas regras de OpenTofu e retire o grant temporário do Tailnet. Os arquivos do lote permanecem no disco.

## Conferir o Gate desmontado no HomeShip

Faça esta verificação entre entregas, com o disco conectado ao PVE e o lote em quarentena. Execute os comandos a partir de `infrastructure/ansible` no controlador com o inventário de produção.

1. Após encerrar o acesso conforme a seção anterior, execute `ansible-playbook -i inventory/hosts.yml playbooks/gate-storage.yml -e gate_storage_standby=true`. O playbook verifica o relé no Hub, o SSH de entrega e a montagem do cliente na VM 200, as exportações NFS e o UUID `58a9af19-1ed0-4488-b08a-c34c35e5ebbf` em `/mnt/gate-4tb` no PVE. O kernel recusa a desmontagem se houver processos usando o disco. Nesse caso, encerre a atividade identificada e repita a operação.
2. Aguarde o próximo ciclo de coleta. No Deck 01, confirme **HD Gate 4 TB** em standby, com o disco presente e a capacidade livre ausente. As métricas esperadas são `pve_gate4tb_present 1` e `pve_gate4tb_mounted 0`. O modo de espera preserva a entrada `nofail` em `/etc/fstab`; o PVE pode voltar a montar o disco no próximo boot.
3. Execute `ansible-playbook -i inventory/hosts.yml playbooks/gate-storage.yml` para restaurar a montagem por UUID e conferir as pastas do lote e do staging no disco de 18 TB. Aguarde a atualização do Deck 01 e confirme `pve_gate4tb_mounted 1`, a capacidade e o espaço livre. A autorização de entrega continua sendo gerenciada por `gate-access.yml`.
