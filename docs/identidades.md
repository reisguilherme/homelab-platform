# Identidades web do HomeServer

O Authelia autentica as contas do catálogo `infrastructure/hub/authelia/users_database.sops.yaml`. O controlador `pve01` usa a identidade Age de produção e aceita alterações pelo checkout revisado de `main`. O arquivo `oidc.sops.yaml` contém o segredo do cliente Proxmox, seu digest, a chave de assinatura e o segredo HMAC do emissor. O Hub recebe o digest do cliente.

## Operação do catálogo

No checkout `/opt/homelab-iac/homelab-platform` do controlador, o administrador pode executar os comandos abaixo em um terminal confiável. Substitua `nome` e os grupos pelos dados autorizados. O helper pede a senha sem eco nos comandos de criação e troca.

```sh
python3 scripts/identities.py add nome --display-name 'Nome' --groups homelab-viewers
python3 scripts/identities.py groups nome --groups homelab-viewers ssh-sftp-drop
python3 scripts/identities.py disable nome
python3 scripts/identities.py enable nome
python3 scripts/identities.py password nome
python3 scripts/identities.py validate
```

O comando `groups` substitui a lista completa de grupos. O helper exige pelo menos um administrador ativo e confirma que cada arquivo recém-cifrado pode ser recuperado antes de substituir a versão anterior. Revise e publique o catálogo cifrado em `main` e execute `ansible-playbook -i inventory/hosts.yml playbooks/hub.yml` a partir de `infrastructure/ansible`. O acesso SSH exige provisionamento separado da chave pública e da política do host.

## Primeiro provisionamento e recuperação

A migração de um Hub existente usa `playbooks/bootstrap-identities.yml`, com as variáveis `initial_username`, `initial_display_name` e `initial_groups` passadas explicitamente. O playbook cifra o arquivo de usuários na VM 100 antes de enviá-lo ao controlador. A senha inicial é gerada no controlador e guardada com Age em `/root/.local/state/homelab-identities/<usuário>.sops.yaml`, em diretório `0700` e arquivo `0600` fora do Git. Para a conta de Gustavo, o arquivo é `/root/.local/state/homelab-identities/gustavo.sops.yaml`. Uma nova execução reaproveita a credencial inicial. Depois de uma troca de senha, o arquivo continua contendo a credencial inicial.

O proprietário pode recuperar o valor em uma sessão privada no próprio controlador com `/usr/local/bin/sops decrypt --extract '["initial_password"]' /root/.local/state/homelab-identities/gustavo.sops.yaml`. A saída é a senha. Execute o comando somente no terminal pessoal do proprietário. A restauração do servidor requer o backup da identidade Age e do arquivo de recuperação fora do repositório.

Em um Hub novo, provisione o inventário, a identidade Age do controlador e a configuração privada `/opt/homelab-hub/.env`. O playbook do Hub usa os dois arquivos SOPS de `main`, prepara os diretórios, valida a configuração na imagem fixada do Authelia e aguarda o healthcheck. Se a ativação falhar, o playbook restaura a configuração anterior a partir do tmpfs privado. Para recuperar uma revisão anterior do catálogo, reverta o commit correspondente e reconcilie o Hub.

## Grupos e serviços

| Grupo | Acesso pela web |
| --- | --- |
| `admins` | Serviços administrativos e Proxmox |
| `homelab-viewers` | HomeShip, incluindo o alias `homeship`, e o cliente Proxmox |
| `pve-auditors` | Cliente Proxmox |
| `media-ops` | HomeShip, Radarr, Sonarr, Prowlarr, Bazarr e qBittorrent |

O acesso usa um fator. O Authelia aplica `deny` por padrão e repete a restrição por grupo no protocolo OIDC para o cliente Proxmox. O BFF do HomeShip e as ACLs do Proxmox aplicam as permissões dentro de cada serviço.
