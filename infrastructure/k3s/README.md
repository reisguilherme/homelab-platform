# K3s — etapa posterior

K3s entra quando o orçamento de recursos e os workloads justificarem sua
operação. A primeira etapa usa Compose dentro das VMs. Este diretório não
contém cluster instalado nem manifests prontos para produção.

Proxmox continua gerindo máquinas virtuais e seus recursos. K3s gerencia
workloads dentro das VMs destinadas ao cluster; ele não substitui as ACL de VM,
o firewall do hipervisor nem a autoridade sobre o hub de arquivos.

Antes de adotar o cluster, definir topologia/quorum, rede, identidade, ingress,
storage classes, restrições de agendamento, segredos, telemetria e restauração.
O contrato `homelab/v1` aceita `runtime: k3s` como declaração; isso não cria RBAC,
NetworkPolicy, PVC ou capacidade. Cada projeto precisa fornecer e comprovar seus
manifests compatíveis. Não apontar bancos para NFS/mergerfs por conveniência.

As decisões e os limites de crescimento estão no
[to-be](../../docs/architecture/to-be.md) e nos
[gaps](../../docs/architecture/gaps.md).
