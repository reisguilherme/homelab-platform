# Tampa do notebook no host Proxmox

Em **16/11/2026**, os logs do host mostraram fechamento da tampa seguido de
suspensão. Foi aplicado somente o [drop-in de configuração do logind](../../infrastructure/proxmox/90-homelab-lid.conf)
em `/etc/systemd/logind.conf.d/90-homelab-lid.conf`:

```ini
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
```

As três opções cobrem a ação do `logind` para tampa na política geral, com
alimentação externa e em dock. `ignore` impede essa ação do `logind`; não
desabilita outras causas de suspensão, políticas de outro software ou falhas
de energia. Drop-ins locais permitem preservar o arquivo principal e as
demais configurações. [Referência oficial de logind.conf](https://www.freedesktop.org/software/systemd/man/latest/logind.conf.html#HandleLidSwitch=).

## Resultado observado

No systemd **257.13** instalado, `systemctl reload systemd-logind` era
suportado e releu a configuração sem alterar PID do serviço ou boot do host.
D-Bus informou `ignore` nas três propriedades. Não foi necessário reboot,
criar unit do host ou reescrever o serviço Lenovo. A releitura é uma operação
do serviço de login existente. [Referência oficial de systemd-logind](https://www.freedesktop.org/software/systemd/man/latest/systemd-logind.service.html#SIGHUP).

O proprietário manteve a tampa fechada por **30 segundos**. Quatro amostras
registraram tampa fechada; o delta dos relógios usado para detectar suspensão
foi inferior a **0,5 segundo**. SSH permaneceu alcançável e as **quatro VMs**
continuaram em execução. Isso aceita o fechamento nesse ensaio. **A
persistência após reboot do host ainda não foi testada.** Não houve ensaio de
nobreak, corte da fonte do HD ou falta total de energia por meio desse teste.

## Aplicar e conferir somente este drop-in

Executar no host autorizado, como root, com a tampa aberta e acesso
administrativo acompanhado. Antes de substituir o destino, registrar se o
arquivo já existe e, nesse caso, guardar uma cópia de referência privada fora
do Git. Não alterar outros arquivos `logind.conf`/drop-ins. Capturas, logs,
boot IDs e inventário de VMs também ficam privados.

Conferir a configuração combinada, a possibilidade de reload e os valores
anteriores de PID/boot:

```sh
systemctl --version
systemctl show systemd-logind -p CanReload -p MainPID
cat /proc/sys/kernel/random/boot_id
systemd-analyze cat-config systemd/logind.conf
```

Prosseguir somente se `CanReload=yes` e o arquivo revisado estiver disponível
no host. O exemplo abaixo parte da raiz do checkout; se o template tiver sido
transferido separadamente, usar seu caminho conferido como origem. Instalar
apenas o destino mostrado e pedir a releitura do serviço:

```sh
install -d -m 0755 /etc/systemd/logind.conf.d
install -m 0644 infrastructure/proxmox/90-homelab-lid.conf /etc/systemd/logind.conf.d/90-homelab-lid.conf
systemctl reload systemd-logind
```

Se reload não for suportado ou falhar, interromper e investigar; não substituir
silenciosamente por restart ou reboot. Conferir novamente PID e boot, a
configuração combinada e os valores efetivamente carregados:

```sh
systemctl show systemd-logind -p CanReload -p MainPID
cat /proc/sys/kernel/random/boot_id
systemd-analyze cat-config systemd/logind.conf
for property in HandleLidSwitch HandleLidSwitchExternalPower HandleLidSwitchDocked; do
    busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager "$property"
done
```

As três respostas precisam ser `s "ignore"`; divergência exige revisar a
precedência dos arquivos. Para repetir o ensaio físico, o proprietário deve
acompanhar o equipamento: obter uma leitura inicial dos relógios, fechar a
tampa por 30 segundos e observar durante a janela:

```sh
busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager LidClosed
qm list
python3 -c 'import time; print(time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC))'
```

Comparar o delta da diferença entre os relógios com a leitura inicial, obter
quatro amostras de `LidClosed=true`, conferir alcance SSH durante a janela e
as quatro VMs em execução. Registrar qualquer suspensão ou perda de acesso;
a mera presença do arquivo não aceita o ensaio. Repetir as conferências após
um próximo reboot autorizado para avaliar a persistência ainda pendente.

## Reverter somente este arquivo

Manter a tampa aberta durante a reversão. Se o destino não existia antes da
aplicação, remover somente o arquivo criado:

```sh
rm -- /etc/systemd/logind.conf.d/90-homelab-lid.conf
systemctl reload systemd-logind
```

Se existia, restaurar a cópia privada anterior **nesse mesmo destino**, em vez
de removê-lo, e executar o reload. Não remover o diretório nem outros
drop-ins, não substituir o arquivo principal e não criar/regravar units.
Repetir as leituras de configuração, D-Bus, PID e boot, comparando com a
política anterior. A reversão pode restabelecer suspensão ao fechar a tampa;
mantê-la aberta até conferir o resultado.

## Fronteira com storage e energia

Após a suspensão, a reconexão USB deixou SMART físico indisponível dentro do
core e `HOLD` conteve a playback. Houve recuperação assistida com parada
normal do Docker/NFS da playback, parada do NFS e desmontagem ext4 no core,
desligamento limpo da VM, inspeção física SMART aprovada e ext4 limpo sem
reparo. O core iniciou com a mesma configuração USB; mount/NFS e prova nova
retornaram, seguidos por `resume` explícito e Jellyfin saudável.

O hash do recibo da captura de backup permaneceu preservado; não houve hash
global do acervo. Essa recuperação e o teste da tampa são evidências
distintas. Supervisor/lease fornecem contenção automática; reintegração
física e readmissão continuam explícitas. O ajuste da tampa não aceita
recuperação USB automática nem substitui nobreak. Seguir o [runbook de storage](storage-core-handoff.md)
e a [arquitetura de energia e recuperação](../architecture/power-recovery.md).
